"""
Background discovery scheduler.
Timer-driven: refreshes keywords from graph, fires searches per keyword,
deduplicates against LanceDB, triggers pipeline for new URLs.
"""
import asyncio
import logging
import os
from config import (
    DISCOVERY_ENABLED,
    DISCOVERY_INTERVAL,
    INTEREST_REFRESH_INTERVAL,
    MAX_URLS_PER_CYCLE,
)

_logger = logging.getLogger(__name__)


class DiscoveryScheduler:
    def __init__(self):
        self._running = False
        self._keywords: list[str] = []
        self._seen_urls: set[str] = set()
        self._in_flight: set[str] = set()
        self._pipeline_func = None

    def _is_new_url(self, url: str) -> bool:
        if url in self._seen_urls or url in self._in_flight:
            return False
        return True

    async def _refresh_keywords(self):
        """Re-extract interests from vault graph."""
        try:
            from core.graph_interests import extract_interests
            keywords = extract_interests()
            self._keywords = keywords
            _logger.info("Discovery: refreshed %d interest keywords", len(keywords))
        except Exception as e:
            _logger.warning("Discovery: failed to refresh keywords: %s", e)

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

        return results

    async def _search_arxiv(self, keyword: str, max_results: int = 3) -> list[dict]:
        """Search arXiv API for keyword."""
        import urllib.request
        import urllib.parse
        import xml.etree.ElementTree as ET

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
        await self._refresh_keywords()
        while self._running:
            try:
                await self._run_discovery_cycle()
            except Exception as e:
                _logger.error("Discovery: cycle failed: %s", e)
            await asyncio.sleep(DISCOVERY_INTERVAL)

    def start(self, pipeline_func=None):
        """Start the scheduler. pipeline_func is the pipeline coroutine to call."""
        if not DISCOVERY_ENABLED:
            _logger.info("Discovery: disabled via DISCOVERY_ENABLED")
            return
        self._running = True
        self._pipeline_func = pipeline_func
        asyncio.create_task(self._scheduler_loop())
        _logger.info("Discovery scheduler started")

    def stop(self):
        self._running = False
        _logger.info("Discovery scheduler stopped")
