"""
Background discovery scheduler.
Timer-driven: refreshes keywords from graph, fires searches per keyword,
deduplicates against LanceDB, triggers pipeline for new URLs.
"""
import asyncio
import json
import logging
import os
import re
import requests
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
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
    purge_keyword as _km_purge,
    suppress_keyword as _km_suppress,
    load_suppressed_keywords as _load_suppressed,
)
from ingesters.web import extract_url
from pathlib import Path

_logger = logging.getLogger(__name__)

KEYWORDS_FILE = Path(VAULT_PATH) / "_keywords"
_SEEN_URLS_FILE = Path.home() / ".personalWiki" / "discovery_seen_urls.json"


class DiscoveryScheduler:
    def __init__(self):
        self._running = False
        self._scheduler_task: asyncio.Task | None = None
        self._keywords: list[str] = []
        self._seen_urls: set[str] = set()
        self._in_flight: set[str] = set()
        self._pipeline_func = None
        # Amplification loop state
        self._url_keyword_lineage: dict[str, str] = {}  # url -> keyword that discovered it
        self._keyword_scores: dict[str, int] = {}       # keyword -> quality score
        self._discovery_cycle_count = 0                  # count for echo chamber guard
        self._warm_seen_urls()
        # Eagerly load keywords in background so /keywords is ready before first poll
        t = threading.Thread(target=self._blocking_refresh, daemon=True)
        t.start()

    def _blocking_refresh(self):
        """Run _refresh_keywords synchronously in a thread (for __init__)."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._refresh_keywords())
        finally:
            loop.close()

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
        """Re-extract interests from vault graph and merge manual keywords."""
        try:
            from core.graph_interests import extract_interests
            keywords = await asyncio.to_thread(extract_interests)
            manual = _load_manual_keywords(KEYWORDS_FILE)
            suppressed = _load_suppressed(KEYWORDS_FILE)
            # Filter out suppressed keywords from graph extraction
            keywords = [kw for kw in keywords if kw not in suppressed]
            merged = list(dict.fromkeys([*keywords, *manual]))
            self._keywords = merged
            _logger.info("Discovery: refreshed %d interest keywords (%d graph + %d manual, %d suppressed)",
                          len(merged), len(keywords), len(manual), len(suppressed))
        except Exception as e:
            _logger.warning("Discovery: failed to refresh keywords: %s", e)

    def add_keyword(self, keyword: str):
        """Add a manual keyword to _keywords and activate it."""
        _km_add(keyword, KEYWORDS_FILE)
        if keyword not in self._keywords:
            self._keywords.append(keyword)
        _logger.info("Discovery: added manual keyword %r", keyword)

    def remove_keyword(self, keyword: str) -> list[str]:
        """Remove keyword from _keywords; purge from vault via purge_keyword."""
        _km_remove(keyword, KEYWORDS_FILE)
        if keyword in self._keywords:
            self._keywords.remove(keyword)
        deleted = _km_purge(keyword, Path(VAULT_PATH))
        _logger.info("Discovery: removed manual keyword %r, purged %d files", keyword, len(deleted))
        return deleted

    def suppress_keyword(self, keyword: str) -> list[str]:
        """Suppress a graph keyword: add to blocklist and purge matching vault files."""
        _km_suppress(keyword, KEYWORDS_FILE)
        if keyword in self._keywords:
            self._keywords.remove(keyword)
        deleted = _km_purge(keyword, Path(VAULT_PATH))
        _logger.info("Discovery: suppressed graph keyword %r, purged %d files", keyword, len(deleted))
        return deleted

    def record_discovery(self, url: str, keyword: str):
        """Record that a URL was discovered via a keyword. Used for cycle detection."""
        if url not in self._url_keyword_lineage:
            self._url_keyword_lineage[url] = keyword

    async def _amplify_from_note(self, note: dict):
        """Extract new keywords from a recently written note and add to pool."""
        from core.keyword_extractor import extract_keywords_from_note

        title = note.get("title", "")
        raw_text = note.get("raw_text", "")

        new_keywords = await asyncio.to_thread(extract_keywords_from_note, title, raw_text)
        if not new_keywords:
            return

        for kw in new_keywords:
            score = self._keyword_scores.get(kw, 0)
            if score < -5:
                continue
            if kw not in self._keywords:
                self._keywords.append(kw)
                _logger.info("Amplification: added keyword %r from note %r", kw, title)

    def _update_keyword_score(self, keyword: str, delta: int):
        """Update score for a keyword. Suppresses if below -5."""
        self._keyword_scores[keyword] = self._keyword_scores.get(keyword, 0) + delta
        score = self._keyword_scores[keyword]
        if score < -5 and keyword in self._keywords:
            self.suppress_keyword(keyword)
            _logger.info("Amplification: suppressed keyword %r (score %d)", keyword, score)

    def _get_explore_keywords(self) -> list[str]:
        """Return 1-2 random explore keywords from a broader pool."""
        explore_pool = [
            "distributed systems",
            "program synthesis",
            "diffusion models",
            "formal verification",
            "compilers",
            "operating systems",
            "network protocols",
        ]
        import random
        available = [k for k in explore_pool if k not in self._keywords]
        return random.sample(available, min(2, len(available)))

    async def _search_keyword(self, keyword: str) -> list[dict]:
        """
        Search across sources for a keyword.
        Returns list of {url, title, snippet, source} dicts.
        Snippets are enriched generically for any source that returned empty ones.
        """
        results = []

        try:
            results.extend(await self._search_arxiv(keyword))
        except Exception as e:
            _logger.warning("Discovery: arXiv search failed for %s: %s", keyword, e)

        try:
            results.extend(self._search_hn(keyword))
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

        # Generic snippet enrichment: fetch content for any result with an empty snippet
        return await self._enrich_snippets(results)

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

    def _search_hn(self, keyword: str, limit: int = 3) -> list[dict]:
        """Search Hacker News via Algolia API."""
        import json, urllib.request
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

    def _search_minimax(self, keyword: str, limit: int = 3) -> list[dict]:
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
            if not url or not url.startswith("http"):
                continue
            try:
                req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as hresp:
                    if hresp.status < 400:
                        real_snippet = ""
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                fetch_result = self._fetch_article_snippet(url)
                                if asyncio.iscoroutine(fetch_result):
                                    real_snippet = loop.run_until_complete(fetch_result)
                                else:
                                    real_snippet = fetch_result
                            finally:
                                loop.close()
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
        """
        results = []

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

        return results

    async def _run_discovery_cycle(self):
        """One discovery pass: search all keywords, ingest new URLs."""
        from core.vector_store import get_store
        store = get_store()

        ingested = 0
        for keyword in self._keywords:
            if ingested >= MAX_URLS_PER_CYCLE:
                break
            results = await self._search_keyword(keyword)
            for result in results:
                url = result["url"]
                if not url or not self._is_new_url(url):
                    continue
                if store.exists(url):
                    self._seen_urls.add(url)
                    self._persist_seen_urls()
                    continue

                _logger.info("Discovery: ingesting %s — %s", url, result["title"])
                self._in_flight.add(url)
                self.record_discovery(url, keyword)  # Track lineage for cycle detection
                try:
                    if self._pipeline_func:
                        asyncio.create_task(self._run_pipeline(url))
                    ingested += 1
                    self._update_keyword_score(keyword, +1)  # Successful ingest
                    self._seen_urls.add(url)
                    self._persist_seen_urls()
                except Exception as e:
                    self._update_keyword_score(keyword, -2)  # Failed/rejected
                    _logger.error("Discovery: failed to queue %s: %s", url, e)
                finally:
                    self._in_flight.discard(url)

                if ingested >= MAX_URLS_PER_CYCLE:
                    break

        # Echo chamber guard: every 5th cycle, inject explore keywords
        self._discovery_cycle_count += 1
        if self._discovery_cycle_count % 5 == 0:
            explore_kws = self._get_explore_keywords()
            for kw in explore_kws:
                if kw not in self._keywords:
                    self._keywords.append(kw)
                    _logger.info("Amplification: explore keyword added %r", kw)

    async def _run_pipeline(self, url: str):
        """Run ingestion pipeline for a single URL."""
        try:
            from pipeline import run_pipeline
            async for _ in run_pipeline(url=url):
                pass
        except Exception as e:
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

    def start(self, pipeline_func=None):
        """Start the scheduler. pipeline_func is the pipeline coroutine to call."""
        if not DISCOVERY_ENABLED:
            _logger.info("Discovery: disabled via DISCOVERY_ENABLED")
            return
        if self._running or self._scheduler_task is not None:
            _logger.warning("Discovery scheduler already running")
            return
        self._running = True
        self._pipeline_func = pipeline_func
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        _logger.info("Discovery scheduler started")

    def stop(self):
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            self._scheduler_task = None
        _logger.info("Discovery scheduler stopped")
