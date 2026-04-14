"""
Background discovery scheduler.
Timer-driven: refreshes keywords from graph, fires searches per keyword,
deduplicates against LanceDB, triggers pipeline for new URLs.
"""
import asyncio
import logging
import os
import re
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
)
from ingesters.web import extract_url
from pathlib import Path

_logger = logging.getLogger(__name__)

INTERESTS_FILE = Path(VAULT_PATH) / ".interests"


class DiscoveryScheduler:
    def __init__(self):
        self._running = False
        self._scheduler_task: asyncio.Task | None = None
        self._keywords: list[str] = []
        self._seen_urls: set[str] = set()
        self._in_flight: set[str] = set()
        self._pipeline_func = None

    def _is_new_url(self, url: str) -> bool:
        if url in self._seen_urls or url in self._in_flight:
            return False
        return True

    async def _refresh_keywords(self):
        """Re-extract interests from vault graph and merge manual keywords."""
        try:
            from core.graph_interests import extract_interests
            keywords = extract_interests()
            manual = _load_manual_keywords(INTERESTS_FILE)
            merged = list(dict.fromkeys([*keywords, *manual]))
            self._keywords = merged
            _logger.info("Discovery: refreshed %d interest keywords (%d graph + %d manual)",
                          len(merged), len(keywords), len(manual))
        except Exception as e:
            _logger.warning("Discovery: failed to refresh keywords: %s", e)

    def add_keyword(self, keyword: str):
        """Add a manual keyword to .interests and activate it in _keywords."""
        try:
            _km_add(keyword, INTERESTS_FILE)
        except ValueError:
            pass  # already in file; still ensure it's in _keywords
        if keyword not in self._keywords:
            self._keywords.append(keyword)
        _logger.info("Discovery: added manual keyword %r", keyword)

    def remove_keyword(self, keyword: str) -> list[str]:
        """Remove keyword from .interests and _keywords; purge from vault via purge_keyword."""
        _km_remove(keyword, INTERESTS_FILE)
        if keyword in self._keywords:
            self._keywords.remove(keyword)
        deleted = _km_purge(keyword, Path(VAULT_PATH))
        _logger.info("Discovery: removed manual keyword %r, purged %d files", keyword, len(deleted))
        return deleted

    async def _search_keyword(self, keyword: str) -> list[dict]:
        """
        Search across sources for a keyword.
        Returns list of {url, title, snippet, source} dicts.
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
            results.extend(self._search_minimax(keyword))
        except Exception as e:
            _logger.warning("Discovery: MiniMax search failed for %s: %s", keyword, e)

        try:
            results.extend(await self._search_desprebursa(keyword))
        except Exception as e:
            _logger.warning("Discovery: DespreBursa search failed for %s: %s", keyword, e)

        return results

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
        Web search via MiniMax chat API using a prompt-based approach.
        Returns list of {url, title, snippet, source}.
        """
        import requests
        import json
        from config import MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_API_URL

        if not MINIMAX_API_KEY:
            return []

        prompt = (
            f'Search the web for: {keyword}\n'
            'Return exactly 3 results as a JSON array with fields: url, title, snippet (max 150 chars).\n'
            'Return ONLY the JSON array, no explanation. Example: '
            '[{"url": "https://...", "title": "...", "snippet": "..."}]'
        )
        headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MINIMAX_MODEL,
            "messages": [
                {"role": "system", "content": "You are a web search assistant. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
        }
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        # Strip markdown code fences if present
        content = content.removeprefix("```json").removeprefix("```").strip()
        results = json.loads(content)
        return [{"url": r["url"], "title": r["title"], "snippet": r["snippet"][:200], "source": "minimax"}
                for r in results[:limit]]

    async def _search_desprebursa(self, keyword: str, limit: int = 5) -> list[dict]:
        """
        Search DespreBursa.ro via sitemap and category pages.
        Returns list of {url, title, snippet, source} dicts.
        """
        results = []

        # Tier 1: Sitemap
        try:
            sitemap_url = "https://www.desprebursa.ro/sitemap.xml"
            req = urllib.request.Request(sitemap_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read().decode("utf-8")
            root = ET.fromstring(data)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            keyword_lower = keyword.lower()
            for url_elem in root.findall("sm:url/sm:loc", ns):
                loc = url_elem.text.strip() if url_elem.text else ""
                if keyword_lower in loc.lower():
                    results.append({
                        "url": loc,
                        "title": loc.split("/")[-1],
                        "snippet": "",
                        "source": "desprebursa",
                    })
                    if len(results) >= limit:
                        return results
        except Exception as e:
            _logger.warning("Discovery: DespreBursa sitemap fetch failed: %s", e)

        # Tier 2: Category page crawl (only if we need more results)
        if len(results) >= limit:
            return results

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
                # Extract article links from HTML
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
                            return results
            except Exception as e:
                _logger.warning("Discovery: DespreBursa category page failed %s: %s", cat_url, e)

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
                    continue

                _logger.info("Discovery: ingesting %s — %s", url, result["title"])
                self._in_flight.add(url)
                try:
                    if self._pipeline_func:
                        asyncio.create_task(self._run_pipeline(url))
                    ingested += 1
                    self._seen_urls.add(url)
                except Exception as e:
                    _logger.error("Discovery: failed to queue %s: %s", url, e)
                finally:
                    self._in_flight.discard(url)

                if ingested >= MAX_URLS_PER_CYCLE:
                    break

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
