"""
Background discovery scheduler.
Timer-driven: refreshes keywords from graph, fires searches per keyword,
deduplicates against LanceDB, triggers pipeline for new URLs.
"""
import asyncio
import json
import logging
import re
import requests
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from core.prose import measure_prose
from config import (
    DISCOVERY_ENABLED,
    DISCOVERY_INTERVAL,
    INTEREST_REFRESH_INTERVAL,
    MAX_URLS_PER_CYCLE,
    VAULT_PATH,
)
from core.keywords_manager import (
    load_manual_keywords as _load_manual_keywords,
    add_keyword as _km_add,
    remove_keyword as _km_remove,
)
from ingesters.web import extract_url
from pathlib import Path
from vault.doctor import cleanup_junk
from core.discovery_link_extractor import DiscoveryLinkExtractor
from core.interest_domain_matcher import InterestDomainMatcher
from core.discovery_logger import get_discovery_logger

_logger = logging.getLogger(__name__)

KEYWORDS_FILE = Path(VAULT_PATH) / "_keywords"
_SEEN_URLS_FILE = Path.home() / ".personalWiki" / "discovery_seen_urls.json"


# ---------------------------------------------------------------------------
# Helper functions (used by DiscoveryScheduler and tests)
# ---------------------------------------------------------------------------

def _measure_prose(text: str) -> tuple[int, float]:
    """Wrapper for core.prose.measure_prose."""
    return measure_prose(text)


def _extract_article_links(html: str, parent_url: str, keyword: str) -> list[str]:
    """Extract candidate article links from HTML of a thin page.

    Filters: same domain only, skips nav/footer/pagination/media links,
    requires article indicators (/article/, /post/, /news/, /blog/, year pattern).
    Returns deduped ordered list (DOM order preserved).
    """
    from urllib.parse import urljoin, urlparse

    SKIP_PATTERNS = ["/nav/", "/menu/", "/footer/", "/header/",
                     "/sidebar/", "/pagination/", "/tag/", "/category/"]
    MEDIA_EXTS = [".jpg", ".png", ".gif", ".pdf", ".mp4", ".zip"]
    ARTICLE_INDICATORS = ["/article/", "/post/", "/news/", "/blog/",
                         "/2024/", "/2025/", "/2026/"]

    parsed_parent = urlparse(parent_url)
    domain = parsed_parent.netloc

    link_re = re.compile(r'href="([^"#]+)"')
    candidates = []

    for match in link_re.finditer(html):
        href = match.group(1)
        full_url = urljoin(parent_url, href)
        parsed = urlparse(full_url)

        # Same domain only
        if parsed.netloc != domain:
            continue

        url_lower = full_url.lower()

        # Skip nav/footer patterns
        if any(p in url_lower for p in SKIP_PATTERNS):
            continue

        # Skip media
        if any(url_lower.endswith(ext) for ext in MEDIA_EXTS):
            continue

        # Must look like an article
        if not any(ind in url_lower for ind in ARTICLE_INDICATORS):
            continue

        candidates.append(full_url)

    return list(dict.fromkeys(candidates))  # dedupe, preserve order


def _pick_best_link(urls: list[str], keyword: str) -> str:
    """Pick best article link from candidates by keyword relevance + slug length.

    Scoring: +10 for keyword in URL, +len(slug)/100 for specificity.
    Returns highest-scoring URL or empty string.
    """
    if not urls:
        return ""

    keyword_lower = keyword.lower()

    # Score each URL
    scored = []
    for url in urls:
        score = 0
        url_lower = url.lower()
        # Keyword match
        if keyword_lower in url_lower:
            score += 10
        # Slug length (longer = more specific article)
        slug = url_lower.split("/")[-1]
        score += len(slug) / 100
        scored.append((score, url))

    scored.sort(reverse=True)
    return scored[0][1]


class DiscoveryScheduler:
    def __init__(self):
        self._running = False
        self._scheduler_task: asyncio.Task | None = None
        self._keywords: list[str] = []
        self._seen_urls: set[str] = set()
        self._in_flight: set[str] = set()
        self._pipeline_func = None
        self._start_lock = asyncio.Lock()
        self._keywords_lock = threading.Lock()
        # Recursive link discovery state
        self._sitemap_queue: asyncio.Queue[str] = asyncio.Queue()  # sitemap URLs pending ingestion
        self._interest_domains: set[str] = set()         # domains discovered via link extraction
        self._warm_seen_urls()
        # Eagerly load keywords in background so /keywords is ready before first poll
        t = threading.Thread(target=self._blocking_refresh, daemon=True)
        t.start()

    def _blocking_refresh(self):
        """Run _refresh_keywords synchronously in a thread (for __init__)."""
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            new_loop.run_until_complete(self._refresh_keywords())
        finally:
            new_loop.close()

    def _warm_seen_urls(self):
        """Populate _seen_urls from disk cache and vector store."""
        # Load from disk cache first
        if _SEEN_URLS_FILE.exists():
            try:
                self._seen_urls = set(json.loads(_SEEN_URLS_FILE.read_text()))
            except Exception:
                pass
        # Also warm from vector store
        try:
            from core.vector_store import get_store
            store = get_store()
            for url in store.get_all_paths():
                self._seen_urls.add(url)
        except Exception as e:
            _logger.debug("Could not warm seen_urls from store: %s", e)

    def _persist_seen_urls(self):
        """Save seen URLs to disk for persistence across restarts."""
        try:
            _SEEN_URLS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _SEEN_URLS_FILE.write_text(json.dumps(list(self._seen_urls)))
        except Exception as e:
            _logger.debug("Could not persist seen_urls: %s", e)

    def _is_new_url(self, url: str) -> bool:
        if url in self._seen_urls or url in self._in_flight:
            return False
        return True

    async def _refresh_keywords(self):
        """Load manual keywords only — graph extraction disabled (amplification off)."""
        try:
            # Graph extraction disabled — keywords are user-owned only
            manual = _load_manual_keywords(KEYWORDS_FILE)
            with self._keywords_lock:
                self._keywords = list(manual)
            _logger.info("Discovery: refreshed %d manual keywords", len(manual))
        except Exception as e:
            _logger.warning("Discovery: failed to refresh keywords: %s", e)

    def get_keywords(self) -> list[str]:
        """Return a copy of active keywords (thread-safe)."""
        with self._keywords_lock:
            return list(self._keywords)

    def add_keyword(self, keyword: str):
        """Add a manual keyword to _keywords and activate it."""
        _km_add(keyword, KEYWORDS_FILE)
        with self._keywords_lock:
            if keyword not in self._keywords:
                self._keywords.append(keyword)
        _logger.info("Discovery: added manual keyword %r", keyword)

    def remove_keyword(self, keyword: str) -> dict:
        """Remove keyword; cascade delete handled by keywords_manager."""
        result = _km_remove(keyword, KEYWORDS_FILE, vault_path=Path(VAULT_PATH))
        with self._keywords_lock:
            if keyword in self._keywords:
                self._keywords.remove(keyword)
        _logger.info("Discovery: removed manual keyword %r, deleted %d files, stripped %d files", keyword, len(result["deleted"]), len(result["stripped"]))
        return result

    async def trigger_cycle(self) -> None:
        """Trigger a single discovery cycle immediately (from UI)."""
        if not self._running:
            _logger.warning("Discovery: trigger ignored — scheduler not running")
            raise RuntimeError("Discovery scheduler is not running")
        _logger.info("Discovery: manual trigger — running one cycle")
        await self._run_discovery_cycle()

    async def _amplify_from_note(self, note: dict):
        """Amplification disabled — keywords are user-owned only."""
        return

    def _get_explore_keywords(self) -> list[str]:
        """Exploration disabled — keywords are user-owned only."""
        return []

    def is_interest_domain_enqueued(self, domain: str) -> bool:
        """Check if a domain was already enqueued for interest discovery."""
        return domain in self._interest_domains

    def _enqueue_interest_domain(self, domain: str) -> None:
        """
        Enqueue an interest domain for sitemap-based discovery.

        Fetches the domain's sitemap, extracts article URLs, and adds them
        to the discovery pipeline for ingestion.
        """
        if domain in self._interest_domains:
            return
        self._interest_domains.add(domain)
        _logger.info("Discovery: enqueued interest domain %s", domain)
        dl_logger = get_discovery_logger()
        dl_logger.record(f"https://{domain}", None, f"link: {domain}", "enqueued")

        # Try to fetch sitemap and extract candidate URLs
        sitemap_urls = self._try_sitemap(domain)
        for url in sitemap_urls:
            if self._is_new_url(url):
                _logger.info("Discovery: discovered via %s: %s", domain, url)
                dl_logger.record(url, None, f"sitemap: {domain}", "enqueued")
                self._sitemap_queue.put_nowait(url)

    def _try_sitemap(self, domain: str) -> list[str]:
        """Try to fetch sitemap for a domain and return article URLs."""
        common_paths = [
            f"https://{domain}/sitemap.xml",
            f"https://{domain}/sitemap-index.xml",
            f"https://www.{domain}/sitemap.xml",
        ]
        for sitemap_url in common_paths:
            try:
                req = urllib.request.Request(
                    sitemap_url,
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read().decode("utf-8")
                root = ET.fromstring(data)
                ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                urls = []
                for url_elem in root.findall("sm:url/sm:loc", ns):
                    loc = url_elem.text.strip() if url_elem.text else ""
                    if loc:
                        urls.append(loc)
                if urls:
                    _logger.info("Discovery: found %d URLs in sitemap for %s", len(urls), domain)
                    return urls
            except Exception:
                continue
        return []

    async def _fetch_html(self, url: str) -> str:
        """Fetch raw HTML for a URL with exponential backoff retry."""
        for attempt in range(3):
            try:
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                if attempt == 2:
                    _logger.debug("Discovery: fetch failed after 3 attempts for %s: %s", url, e)
                    return ""
                wait = 2 ** attempt
                await asyncio.sleep(wait)
        return ""

    async def _search_keyword(self, keyword: str) -> list[dict]:
        """
        Search across sources for a keyword.
        Returns list of {url, title, snippet, source} dicts.
        Snippets are enriched generically for any source that returned empty ones.
        Skips URLs already processed (exists in LanceDB) for idempotency.
        """
        results = []

        try:
            results.extend(await self._search_arxiv(keyword))
        except Exception as e:
            _logger.warning("Discovery: arXiv search failed for %s: %s", keyword, e)

        try:
            results.extend(await self._search_hn(keyword))
        except Exception as e:
            _logger.warning("Discovery: HN search failed for %s: %s", keyword, e)

        try:
            results.extend(await self._search_minimax(keyword))
        except Exception as e:
            _logger.warning("Discovery: MiniMax search failed for %s: %s", keyword, e)

        try:
            results.extend(await self._search_desprebursa(keyword))
        except Exception as e:
            _logger.warning("Discovery: DespreBursa search failed for %s: %s", keyword, e)

        # Filter out already-processed URLs for idempotency
        from core.vector_store import get_store
        store = get_store()
        filtered = [r for r in results if not store.exists(r["url"])]
        if len(filtered) < len(results):
            skipped = len(results) - len(filtered)
            _logger.debug("Discovery: skipped %d already-processed URLs", skipped)

        # Generic snippet enrichment: fetch content for any result with an empty snippet
        return await self._enrich_snippets(filtered)

    async def _enrich_snippets(self, results: list[dict]) -> list[dict]:
        """Post-process: fetch article content for any result with an empty snippet.

        Works generically for any source. arXiv/HN/MiniMax already return real snippets
        so this is mostly a no-op for them. DespreBursa also fetches its own snippets,
        so this is a fallback for any future source that returns empty ones.
        """
        async def fetch_one(result: dict) -> dict:
            if result.get("snippet"):
                return result
            url = result.get("url", "")
            if not url:
                return result
            snippet = await self._fetch_article_snippet(url)
            result["snippet"] = snippet
            return result

        return await asyncio.gather(*[fetch_one(r) for r in results])

    async def _fetch_article_snippet(self, url: str) -> str:
        """Fetch article page and extract first meaningful paragraph as snippet."""
        try:
            text = await extract_url(url)
            for para in text.split("\n\n"):
                para = para.strip()
                if len(para) > 80:
                    return para[:200]
            return ""
        except Exception:
            return ""

    async def _search_arxiv(self, keyword: str, max_results: int = 3) -> list[dict]:
        """Search arXiv API for keyword."""
        import urllib.parse

        if " " in keyword:
            query = urllib.parse.quote(f'all:"{keyword}"')
        else:
            query = urllib.parse.quote(f"all:{keyword}")
        url = f"http://export.arxiv.org/api/query?search_query={query}&max_results={max_results}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = resp.read().decode("utf-8")
        root = ET.fromstring(data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        results = []
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns)
            link = entry.find("atom:id", ns)
            summary = entry.find("atom:summary", ns)
            results.append({
                "url": link.text.strip() if link is not None else "",
                "title": title.text.strip().replace("\n", " ") if title is not None else "",
                "snippet": summary.text.strip().replace("\n", " ")[:200] if summary is not None else "",
                "source": "arxiv",
            })
        return results

    async def _search_hn(self, keyword: str, limit: int = 3) -> list[dict]:
        """Search Hacker News via Algolia API."""
        import json
        import urllib.request

        def _blocking_search():
            url = "https://hn.algolia.com/api/v1/search"
            params = f"?query={urllib.request.quote(keyword)}&tags=story&hitsPerPage={limit}"
            with urllib.request.urlopen(url + params, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = []
            for hit in data.get("hits", []):
                results.append({
                    "url": hit.get("url", f"https://news.ycombinator.com/item?id={hit.get('objectID')}"),
                    "title": hit.get("title", ""),
                    "snippet": hit.get("excerpt", "")[:200],
                    "source": "hn",
                })
            return results

        return await asyncio.to_thread(_blocking_search)

    async def _search_minimax(self, keyword: str, limit: int = 3) -> list[dict]:
        """
        Web search via MiniMax chat API using function-calling hybrid.

        Round 1: Sends the request with a 'web_search' tool definition. If MiniMax
        returns tool_calls, the arguments contain real URLs from an actual web search.

        Round 2 (fallback): If no tool_calls came back (tool unavailable or error),
        falls back to regex-extracting https:// URLs from the text response and
        HEAD-validating each one before returning.

        Returns list of {url, title, snippet, source}.
        """
        from config import MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_API_URL

        if not MINIMAX_API_KEY:
            return []

        # Define the web_search tool for function-calling
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for current information. Returns real URLs.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "The search query"},
                        },
                        "required": ["query"],
                    },
                },
            }
        ]

        prompt = f"Search the web for: {keyword}"
        headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MINIMAX_MODEL,
            "messages": [
                {"role": "system", "content": "You are a web search assistant. Use the web_search tool to find real, current URLs for the given query."},
                {"role": "user", "content": prompt},
            ],
            "tools": tools,
            "tool_choice": {"type": "function", "function": {"name": "web_search"}},
        }
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Extract tool_calls if present (Round 1: real URLs from web search tool)
        raw_urls = []
        message = data.get("choices", [{}])[0].get("message", {})
        tool_calls = message.get("tool_calls", [])
        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                args = func.get("arguments", "{}")
                try:
                    arguments = json.loads(args)
                    results_list = arguments.get("results", arguments.get("urls", []))
                    if isinstance(results_list, list):
                        for item in results_list:
                            if isinstance(item, dict):
                                raw_urls.append({
                                    "url": item.get("url", ""),
                                    "title": item.get("title", keyword),
                                    "snippet": item.get("snippet", ""),
                                })
                            elif isinstance(item, str) and item.startswith("http"):
                                raw_urls.append({"url": item, "title": keyword, "snippet": ""})
                except (json.JSONDecodeError, TypeError) as e:
                    _logger.debug("Discovery: failed to parse tool_call arguments: %s", e)
        else:
            # Round 2 fallback: extract https:// URLs from text content via regex
            # This handles cases where MiniMax doesn't invoke the tool but still
            # returns URLs in its text response (hallucinated but we HEAD-validate them)
            content = (message.get("content") or "").strip()
            if not content:
                _logger.warning("Discovery: MiniMax returned empty content for %s", keyword)
                return []
            content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

            # Try to parse as JSON first
            try:
                decoder = json.JSONDecoder()
                parsed, _ = decoder.raw_decode(content)
                if isinstance(parsed, list):
                    raw_urls = parsed
            except (json.JSONDecodeError, TypeError):
                # Fall back to regex URL extraction from any text format
                url_pattern = re.compile(r"https://[^\s\)\]'\"<>]+")
                for match in url_pattern.finditer(content):
                    url = match.group(0).rstrip(".,;:)")
                    raw_urls.append({"url": url, "title": keyword, "snippet": ""})

        if not raw_urls:
            _logger.warning("Discovery: MiniMax returned no URLs for %s", keyword)
            return []

        # HEAD-validate each URL and fetch real snippets via Crawl4AI
        validated = []
        for r in raw_urls:
            url = r.get("url", "")
            if not url or not url.startswith("https"):
                continue
            try:
                req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as hresp:
                    if hresp.status < 400:
                        real_snippet = ""
                        try:
                            real_snippet = await self._fetch_article_snippet(url)
                        except Exception:
                            pass

                        validated.append({
                            "url": url,
                            "title": r.get("title", keyword),
                            "snippet": real_snippet[:200] if real_snippet else r.get("snippet", "")[:200],
                            "source": "minimax",
                        })
            except Exception:
                _logger.debug("Discovery: MiniMax URL failed HEAD check, dropping: %s", url)
            if len(validated) >= limit:
                break

        return validated

    async def _search_desprebursa(self, keyword: str, limit: int = 5) -> list[dict]:
        """
        Search DespreBursa.ro via sitemap and category pages.
        Returns list of {url, title, snippet, source} dicts with real content.
        Also extracts outbound links from article pages and enqueues interest domains.
        """
        results = []

        # Initialize link extractor for recursive discovery
        link_extractor = DiscoveryLinkExtractor(matcher=InterestDomainMatcher())

        # Tier 1: Sitemap — stop early if we hit limit
        try:
            sitemap_url = "https://www.desprebursa.ro/sitemap.xml"
            req = urllib.request.Request(sitemap_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read().decode("utf-8")
            root = ET.fromstring(data)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            keyword_lower = keyword.lower()
            for url_elem in root.findall("sm:url/sm:loc", ns):
                if len(results) >= limit:
                    break
                loc = url_elem.text.strip() if url_elem.text else ""
                if keyword_lower in loc.lower():
                    results.append({
                        "url": loc,
                        "title": loc.split("/")[-1],
                        "snippet": "",
                        "source": "desprebursa",
                    })
        except Exception as e:
            _logger.warning("Discovery: DespreBursa sitemap fetch failed: %s", e)

        # If sitemap gave us enough results, skip category crawling entirely
        if len(results) >= limit:
            urls = [r["url"] for r in results]
            snippets = await asyncio.gather(*[self._fetch_article_snippet(u) for u in urls])
            for r, snippet in zip(results, snippets):
                if snippet:
                    r["snippet"] = snippet
            # Extract links from article pages and enqueue interest domains
            await self._extract_and_enqueue_links(urls, link_extractor)
            return results

        # Tier 2: Category page crawl — only if we need more results
        category_pages = [
            "https://www.desprebursa.ro/categorii-publicatii/bvb",
            "https://www.desprebursa.ro/categorii-publicatii/companii",
            "https://www.desprebursa.ro/categorii-publicatii/macro-piete",
            "https://www.desprebursa.ro/categorii-publicatii/strategie",
            "https://www.desprebursa.ro/categorii-publicatii/briefings",
        ]
        keyword_lower = keyword.lower()
        for cat_url in category_pages:
            if len(results) >= limit:
                break
            try:
                text = await extract_url(cat_url)
                link_pattern = re.compile(r'href="(https://www\.desprebursa\.ro/[^"#]+)"')
                for match in link_pattern.finditer(text):
                    url = match.group(1)
                    if keyword_lower in url.lower():
                        results.append({
                            "url": url,
                            "title": url.split("/")[-1],
                            "snippet": "",
                            "source": "desprebursa",
                        })
                        if len(results) >= limit:
                            break
            except Exception as e:
                _logger.warning("Discovery: DespreBursa category page failed %s: %s", cat_url, e)

        # Fetch snippets for found articles concurrently
        if results:
            urls = [r["url"] for r in results]
            snippets = await asyncio.gather(*[self._fetch_article_snippet(u) for u in urls])
            for r, snippet in zip(results, snippets):
                if snippet:
                    r["snippet"] = snippet
            # Extract links from article pages and enqueue interest domains
            await self._extract_and_enqueue_links(urls, link_extractor)

        return results

    async def _extract_and_enqueue_links(self, urls: list[str], link_extractor: DiscoveryLinkExtractor) -> None:
        """Fetch HTML for URLs and process links via link extractor."""
        if not urls:
            return
        html_results = await asyncio.gather(*[self._fetch_html(u) for u in urls])
        for url, html in zip(urls, html_results):
            if html:
                try:
                    link_extractor.process_page_links(url, html, self)
                except Exception as e:
                    _logger.debug("Discovery: link extraction failed for %s: %s", url, e)

    async def _run_discovery_cycle(self):
        """One discovery pass: search all keywords, ingest new URLs, extract links."""
        from core.vector_store import get_store
        store = get_store()

        # Initialize link extractor for recursive discovery
        link_extractor = DiscoveryLinkExtractor(matcher=InterestDomainMatcher())

        ingested = 0
        seen_this_cycle: set[str] = set()
        for keyword in self.get_keywords():
            if ingested >= MAX_URLS_PER_CYCLE:
                break
            results = await self._search_keyword(keyword)
            for result in results:
                url = result["url"]
                if not url or not self._is_new_url(url):
                    continue
                if store.exists(url):
                    self._seen_urls.add(url)
                    continue

                _logger.info("Discovery: ingesting %s — %s", url, result["title"])
                self._in_flight.add(url)
                dl_logger = get_discovery_logger()
                dl_logger.record(url, result.get("title"), f"keyword: {keyword}", "enqueued")
                try:
                    if self._pipeline_func:
                        await self._run_pipeline(url, keyword=keyword)
                    ingested += 1
                    self._seen_urls.add(url)

                    # Recursive link discovery: extract links from the crawled page
                    # and enqueue any new interest domains found
                    try:
                        html = await self._fetch_html(url)
                        if html:
                            link_extractor.process_page_links(url, html, self)
                    except Exception as e:
                        _logger.debug("Discovery: link extraction failed for %s: %s", url, e)
                except Exception as e:
                    _logger.error("Discovery: failed to queue %s: %s", url, e)
                finally:
                    self._in_flight.discard(url)

                if ingested >= MAX_URLS_PER_CYCLE:
                    break

        # Persist seen URLs once after the cycle
        self._persist_seen_urls()

        # Phase 2: drain sitemap queue
        while ingested < MAX_URLS_PER_CYCLE:
            try:
                url = self._sitemap_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if url in seen_this_cycle or store.exists(url):
                self._seen_urls.add(url)
                continue

            seen_this_cycle.add(url)
            await self._run_pipeline(url)
            ingested += 1
            self._seen_urls.add(url)

        # Write daily digest
        from core.digest_writer import write_daily_digest
        from datetime import date

        today_str = date.today().isoformat()
        events = get_discovery_logger().today()
        if events:
            write_daily_digest([dict(e) for e in events], today_str)

        # Junk cleanup — remove video notes with no transcript
        try:
            deleted = cleanup_junk()
            if deleted:
                _logger.info("Junk cleanup: removed %d notes", len(deleted))
        except Exception as e:
            _logger.warning("Junk cleanup failed: %s", e)

    async def _run_pipeline(self, url: str, keyword: str | None = None):
        """Run ingestion pipeline for a single URL."""
        dl_logger = get_discovery_logger()
        try:
            from pipeline import run_pipeline
            async for _ in run_pipeline(
                url=url, is_discovery=True, source_keyword=keyword,
                keywords=[keyword] if keyword else [],
            ):
                pass
            dl_logger.update_status(url, "ingested")
        except Exception as e:
            dl_logger.update_status(url, "failed", error=str(e))
            _logger.error("Discovery: pipeline failed for %s: %s", url, e)

    async def _scheduler_loop(self):
        """Main timer loop."""
        last_refresh = time.monotonic()
        await self._refresh_keywords()
        while self._running:
            elapsed = time.monotonic() - last_refresh
            sleep_time = min(DISCOVERY_INTERVAL, max(0, INTEREST_REFRESH_INTERVAL - elapsed))
            await asyncio.sleep(sleep_time)

            if elapsed >= INTEREST_REFRESH_INTERVAL:
                await self._refresh_keywords()
            last_refresh = time.monotonic()

            try:
                await self._run_discovery_cycle()
            except Exception as e:
                _logger.error("Discovery: cycle failed: %s", e)

    async def start(self, pipeline_func=None):
        """Start the scheduler. pipeline_func is the pipeline coroutine to call."""
        if not DISCOVERY_ENABLED:
            _logger.info("Discovery: disabled via DISCOVERY_ENABLED")
            return
        async with self._start_lock:
            if self._running or self._scheduler_task is not None:
                _logger.warning("Discovery scheduler already running")
                return
            self._pipeline_func = pipeline_func
            # Eagerly refresh keywords so /keywords is never empty on first request
            await self._refresh_keywords()
            self._running = True
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())
            _logger.info("Discovery scheduler started")

    def stop(self):
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            self._scheduler_task = None
        _logger.info("Discovery scheduler stopped")
