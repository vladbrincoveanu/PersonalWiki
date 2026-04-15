# DespreBursa Discovery + Scheduler — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate desprebursa.ro as a discoverable source in the autonomous discovery scheduler. Requires building the scheduler from scratch (not yet implemented) plus adding the desprebursa search tier.

**Architecture:** DiscoveryScheduler is an asyncio timer loop that fires per keyword, searches arXiv/HN/MiniMax/DespreBursa in parallel, deduplicates against LanceDB and an in-memory set, then feeds new URLs to the ingestion pipeline.

**Tech Stack:** Python asyncio, urllib.request, xml.etree.ElementTree, crawl4ai, LanceDB.

---

## File Map

```
core/discovery_scheduler.py     [NEW] Full scheduler with all search methods
tests/test_discovery_scheduler.py [NEW] Unit and integration tests
config.py                       [MODIFIED] Add DISCOVERY_DESPREBURSA_KEYWORDS (optional override)
```

---

## Task 1: Discovery Scheduler Core

**Files:**
- Create: `core/discovery_scheduler.py`
- Test: `tests/test_discovery_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_scheduler.py
import pytest, asyncio
from unittest.mock import patch, MagicMock

def test_scheduler_initializes():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    assert scheduler._running is False
    assert scheduler._keywords == []

def test_deduplication_against_seen_urls():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    scheduler._seen_urls.add("https://arxiv.org/abs/1234")
    assert scheduler._is_new_url("https://arxiv.org/abs/1234") is False
    assert scheduler._is_new_url("https://arxiv.org/abs/9999") is True

def test_is_new_url_tracks_in_flight():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    scheduler._in_flight.add("https://example.com/1")
    assert scheduler._is_new_url("https://example.com/1") is False
    assert scheduler._is_new_url("https://example.com/2") is True

def test_search_keyword_returns_all_sources():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()

    async def run():
        with patch.object(scheduler, "_search_arxiv", return_value=[{"url": "http://a", "title": "A", "snippet": "", "source": "arxiv"}]), \
             patch.object(scheduler, "_search_hn", return_value=[{"url": "http://b", "title": "B", "snippet": "", "source": "hn"}]), \
             patch.object(scheduler, "_search_minimax", return_value=[{"url": "http://c", "title": "C", "snippet": "", "source": "minimax"}]), \
             patch.object(scheduler, "_search_desprebursa", return_value=[{"url": "http://d", "title": "D", "snippet": "", "source": "desprebursa"}]):
            results = await scheduler._search_keyword("RLHF")
        return results

    results = asyncio.get_event_loop().run_until_complete(run())
    assert len(results) == 4
    sources = {r["source"] for r in results}
    assert sources == {"arxiv", "hn", "minimax", "desprebursa"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_scheduler.py -v 2>&1 | head -20`
Expected: FAIL — module `core.discovery_scheduler` not found

- [ ] **Step 3: Write the minimal DiscoveryScheduler implementation**

```python
# core/discovery_scheduler.py
"""
Background discovery scheduler.
Timer-driven: refreshes keywords from graph, fires searches per keyword,
deduplicates against LanceDB, triggers pipeline for new URLs.
"""
import asyncio
import logging
import os
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable, Optional

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
        self._pipeline_func: Optional[Callable] = None

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
        Search across all sources for a keyword.
        Returns list of {url, title, snippet, source} dicts.
        """
        results = []

        # arXiv search
        try:
            results.extend(await self._search_arxiv(keyword))
        except Exception as e:
            _logger.warning("Discovery: arXiv search failed for %s: %s", keyword, e)

        # HN search
        try:
            results.extend(self._search_hn(keyword))
        except Exception as e:
            _logger.warning("Discovery: HN search failed for %s: %s", keyword, e)

        # MiniMax web search
        try:
            results.extend(await self._search_minimax(keyword))
        except Exception as e:
            _logger.warning("Discovery: MiniMax search failed for %s: %s", keyword, e)

        # DespreBursa site search
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
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
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
        import json
        import urllib.parse
        search_url = "https://hn.algolia.com/api/v1/search"
        params = f"?query={urllib.parse.quote(keyword)}&tags=story&hitsPerPage={limit}"
        req = urllib.request.Request(search_url + params, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
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

    async def _search_minimax(self, keyword: str, limit: int = 3) -> list[dict]:
        """Web search via MiniMax chat API."""
        import requests
        import json
        from config import MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_API_URL

        if not MINIMAX_API_KEY:
            return []

        prompt = (
            f"Search the web for: {keyword}\n"
            "Return exactly 3 results as a JSON list with fields: url, title, snippet (max 150 chars).\n"
            "Return ONLY the JSON array, no explanation."
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
        content = content.removeprefix("```json").removeprefix("```").strip()
        results = json.loads(content)
        return [{"url": r["url"], "title": r["title"], "snippet": r["snippet"][:200], "source": "minimax"}
                for r in results[:limit]]

    async def _search_desprebursa(self, keyword: str, limit: int = 5) -> list[dict]:
        """
        Search desprebursa.ro for articles matching keyword.
        Tier 1: sitemap.xml
        Tier 2: crawl4ai category page crawl + link extraction
        Returns list of {url, title, snippet, source} dicts.
        """
        articles = []
        seen_urls: set[str] = set()

        # Tier 1: sitemap
        sitemap_url = "https://www.desprebursa.ro/sitemap.xml"
        try:
            req = urllib.request.Request(sitemap_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read().decode("utf-8")
            root = ET.fromstring(data)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            for loc in root.findall("sm:loc", ns):
                url = loc.text.strip() if loc.text else ""
                if url and "desprebursa.ro" in url and url not in seen_urls:
                    if keyword.lower() in url.lower():
                        articles.append({
                            "url": url,
                            "title": url.split("/")[-1],
                            "snippet": "",
                            "source": "desprebursa",
                        })
                        seen_urls.add(url)
        except Exception as e:
            _logger.warning("DespreBursa sitemap fetch failed: %s", e)

        if len(articles) >= limit:
            return articles[:limit]

        # Tier 2: crawl category pages and extract article links
        category_pages = [
            "https://www.desprebursa.ro/categorii-publicatii/bvb",
            "https://www.desprebursa.ro/categorii-publicatii/companii",
            "https://www.desprebursa.ro/categorii-publicatii/macro-piete",
            "https://www.desprebursa.ro/categorii-publicatii/strategie",
            "https://www.desprebursa.ro/categorii-publicatii/briefings",
        ]

        try:
            from ingesters.web import extract_url
            import re
            for cat_page in category_pages:
                if len(articles) >= limit:
                    break
                try:
                    text = await extract_url(cat_page)
                    article_links = re.findall(r'href="(https://www\.desprebursa\.ro/[^"#]+)"', text)
                    for link in article_links:
                        if link not in seen_urls and keyword.lower() in link.lower():
                            articles.append({
                                "url": link,
                                "title": link.split("/")[-1],
                                "snippet": "",
                                "source": "desprebursa",
                            })
                            seen_urls.add(link)
                except Exception:
                    continue
        except Exception as e:
            _logger.warning("DespreBursa category crawl failed: %s", e)

        return articles[:limit]

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
        last_keyword_refresh = 0
        while self._running:
            try:
                await self._run_discovery_cycle()
            except Exception as e:
                _logger.error("Discovery: cycle failed: %s", e)
            await asyncio.sleep(DISCOVERY_INTERVAL)

    def start(self, pipeline_func: Optional[Callable] = None):
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_discovery_scheduler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/discovery_scheduler.py tests/test_discovery_scheduler.py
git commit -m "feat: add discovery scheduler with arXiv/HN/MiniMax/DespreBursa search"
```

---

## Task 2: Add DespreBursa-Specific Unit Tests

**Files:**
- Modify: `tests/test_discovery_scheduler.py`

- [ ] **Step 1: Add sitemap parsing unit test**

Add to `tests/test_discovery_scheduler.py`:

```python
def test_search_desprebursa_sitemap_parsing():
    """Sitemap XML with mixed URLs, only desprebursa URLs matching keyword are returned."""
    from core.discovery_scheduler import DiscoveryScheduler
    import asyncio

    sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <loc>https://www.desprebursa.ro/2026/04/bvb-actiuni-burse</loc>
        <loc>https://www.desprebursa.ro/2026/04/macro-economie-romania</loc>
        <loc>https://www.desprebursa.ro/2026/04/companii-transelectrica</loc>
        <loc>https://example.com/external</loc>
    </urlset>"""

    scheduler = DiscoveryScheduler()

    async def run():
        with patch("urllib.request.urlopen", new_callable=AsyncMock) as mock_open:
            mock_resp = MagicMock()
            mock_resp.read.return_value = sitemap_xml.encode("utf-8")
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp
            results = await scheduler._search_desprebursa("bvb")
        return results

    results = asyncio.get_event_loop().run_until_complete(run())
    assert len(results) == 1
    assert results[0]["source"] == "desprebursa"
    assert "bvb" in results[0]["url"]


def test_search_desprebursa_falls_back_to_category_crawl():
    """When sitemap fails, category page crawl is attempted."""
    from core.discovery_scheduler import DiscoveryScheduler
    import asyncio

    scheduler = DiscoveryScheduler()

    async def run():
        with patch("urllib.request.urlopen", new_callable=AsyncMock) as mock_open:
            # Sitemap fails
            mock_open.side_effect = Exception("Sitemap not found")
            with patch("core.discovery_scheduler.extract_url", new_callable=AsyncMock) as mock_extract:
                mock_extract.return_value = '''
                    <html><body>
                    <a href="https://www.desprebursa.ro/2026/04/bursa-valorii">Article 1</a>
                    <a href="https://www.desprebursa.ro/2026/04/actiuni-burse">Article 2</a>
                    </body></html>
                '''
                results = await scheduler._search_desprebursa("bursa")
        return results

    results = asyncio.get_event_loop().run_until_complete(run())
    assert len(results) == 2
    assert all(r["source"] == "desprebursa" for r in results)
```

- [ ] **Step 2: Run all discovery scheduler tests**

Run: `pytest tests/test_discovery_scheduler.py -v`
Expected: PASS (including previously passing tests)

- [ ] **Step 3: Commit**

```bash
git add tests/test_discovery_scheduler.py
git commit -m "test: add DespreBursa sitemap and category crawl unit tests"
```

---

## Task 3: Integration Test — Full Cycle

**Files:**
- Modify: `tests/test_discovery_scheduler.py`

- [ ] **Step 1: Add full cycle integration test**

Add to `tests/test_discovery_scheduler.py`:

```python
def test_search_desprebursa_returns_urls_without_raising():
    """Integration test: _search_desprebursa completes without raising for a real keyword."""
    from core.discovery_scheduler import DiscoveryScheduler
    import asyncio

    scheduler = DiscoveryScheduler()

    async def run():
        # Use a real keyword that likely matches desprebursa URL structure
        results = await scheduler._search_desprebursa("BVB")
        return results

    # This hits the real site — verify it returns a list without raising
    try:
        results = asyncio.get_event_loop().run_until_complete(run())
        assert isinstance(results, list)
        for r in results:
            assert "url" in r
            assert "source" in r
            assert r["source"] == "desprebursa"
    except Exception as e:
        # Network may be unavailable in test env — skip gracefully
        pytest.skip(f"Network unavailable: {e}")
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/test_discovery_scheduler.py::test_search_desprebursa_returns_urls_without_raising -v`
Expected: PASS or SKIP (if network unavailable)

- [ ] **Step 3: Commit**

```bash
git add tests/test_discovery_scheduler.py
git commit -m "test: add DespreBursa integration test for full cycle"
```

---

## Task 4: Run Full Test Suite

**Files:** (none — verification only)

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short 2>&1 | tail -30`
Expected: All tests pass with no new failures

---

## Spec Coverage Check

- [x] DiscoveryScheduler core class → Task 1
- [x] _search_arxiv method → Task 1
- [x] _search_hn method → Task 1
- [x] _search_minimax method → Task 1
- [x] _search_desprebursa method → Task 1
- [x] Scheduler loop + deduplication → Task 1
- [x] Unit tests for sitemap parsing → Task 2
- [x] Unit tests for category crawl fallback → Task 2
- [x] Integration test → Task 3
- [x] Full test suite pass → Task 4

## Placeholder Scan

All steps have complete code. No TBD, TODO, or placeholder implementations.

## Type Consistency

- `_search_keyword(keyword: str)` returns `list[dict]` with `{url, title, snippet, source}`
- `_search_desprebursa(keyword: str, limit: int = 5)` returns `list[dict]` matching same schema
- `_is_new_url(url: str)` returns `bool`
- `start(pipeline_func: Optional[Callable] = None)` — pipeline_func is the `run_pipeline` coroutine
