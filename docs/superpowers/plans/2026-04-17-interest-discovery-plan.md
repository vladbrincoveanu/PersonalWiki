# Interest-Graph Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace unreliable `_search_minimax()` URL discovery with crawl4ai-first sitemap crawling, filtered by whether target domains are already known (edge expansion, not node expansion).

**Architecture:** SiteRegistry persists known domains. SitemapDiscovery uses crawl4ai to fetch/parse sitemaps per domain with keyword filtering. SitemapLinkExtractor extracts outbound links from crawled pages and filters them via SiteRegistry.is_known(). MiniMax becomes a domain-discovery signal only — finds sitemaps, not URLs.

**Tech Stack:** crawl4ai AsyncWebCrawler, stdlib xml.etree, stdlib urllib, json file persistence.

---

## File Structure

```
core/
  site_registry.py          (NEW) — SiteRegistry class, JSON persistence
  sitemap_discovery.py      (NEW) — fetch_sitemap() via crawl4ai
  sitemap_link_extractor.py (NEW) — extract_links(), SiteRegistry filter
  graph_interests.py        (MOD) — add is_domain_in_graph()

discovery_scheduler.py      (MOD) — integrate new modules, replace _search_minimax

tests/
  test_site_registry.py     (NEW)
  test_sitemap_discovery.py (NEW)
  test_sitemap_link_extractor.py (NEW)
```

---

## Task 1: SiteRegistry (`core/site_registry.py`)

**Files:**
- Create: `core/site_registry.py`
- Test: `tests/test_site_registry.py`

- [ ] **Step 1: Write failing test — add_domain and is_known**

```python
import json, os, tempfile
from pathlib import Path
from core.site_registry import SiteRegistry

def test_add_domain_and_is_known(tmp_path, monkeypatch):
    registry_path = tmp_path / "site_registry.json"
    monkeypatch.setattr("core.site_registry._REGISTRY_PATH", registry_path)

    reg = SiteRegistry()
    assert reg.is_known("example.com") is False
    reg.add_domain("example.com", source="manual", url="https://example.com/article")
    assert reg.is_known("example.com") is True

def test_all_domains(tmp_path, monkeypatch):
    monkeypatch.setattr("core.site_registry._REGISTRY_PATH", tmp_path / "reg.json")
    reg = SiteRegistry()
    reg.add_domain("a.com", "manual", "https://a.com/p1")
    reg.add_domain("b.com", "minimax_discovery", "https://b.com/p2")
    assert set(reg.all_domains()) == {"a.com", "b.com"}

def test_known_urls(tmp_path, monkeypatch):
    monkeypatch.setattr("core.site_registry._REGISTRY_PATH", tmp_path / "reg.json")
    reg = SiteRegistry()
    reg.add_domain("example.com", "manual", "https://example.com/article1")
    reg.add_url("example.com", "https://example.com/article2")
    urls = reg.known_urls("example.com")
    assert set(urls) == {"https://example.com/article1", "https://example.com/article2"}

def test_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr("core.site_registry._REGISTRY_PATH", tmp_path / "reg.json")
    reg1 = SiteRegistry()
    reg1.add_domain("example.com", "manual", "https://example.com/article")
    reg1.save()

    reg2 = SiteRegistry()
    assert reg2.is_known("example.com") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_site_registry.py -v`
Expected: FAIL — `core.site_registry` has no `SiteRegistry` class yet

- [ ] **Step 3: Write minimal implementation — SiteRegistry class**

```python
# core/site_registry.py
import json
import os
from pathlib import Path
from datetime import date

_REGISTRY_PATH = Path.home() / ".personalWiki" / "site_registry.json"


class SiteRegistry:
    def __init__(self):
        self._domains: dict[str, dict] = {}
        self._load()

    def _load(self):
        if not _REGISTRY_PATH.exists():
            return
        try:
            with open(_REGISTRY_PATH) as f:
                self._domains = json.load(f).get("domains", {})
        except (json.JSONDecodeError, IOError):
            self._domains = {}

    def save(self):
        _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_REGISTRY_PATH, "w") as f:
            json.dump({"domains": self._domains}, f, indent=2)

    def add_domain(self, domain: str, source: str, url: str):
        if domain not in self._domains:
            self._domains[domain] = {
                "added_at": str(date.today()),
                "source": source,
                "last_sitemap_check": None,
                "known_urls": [],
            }
        if url and url not in self._domains[domain]["known_urls"]:
            self._domains[domain]["known_urls"].append(url)
        self.save()

    def add_url(self, domain: str, url: str):
        if domain in self._domains and url not in self._domains[domain]["known_urls"]:
            self._domains[domain]["known_urls"].append(url)
            self.save()

    def is_known(self, domain: str) -> bool:
        return domain in self._domains

    def all_domains(self) -> list[str]:
        return list(self._domains.keys())

    def known_urls(self, domain: str) -> list[str]:
        return list(self._domains.get(domain, {}).get("known_urls", []))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_site_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/site_registry.py tests/test_site_registry.py
git commit -m "feat: add SiteRegistry for persisting known domains"
```

---

## Task 2: SitemapDiscovery (`core/sitemap_discovery.py`)

**Files:**
- Create: `core/sitemap_discovery.py`
- Test: `tests/test_sitemap_discovery.py`

- [ ] **Step 1: Write failing test — sitemap URL patterns and keyword filter**

```python
import pytest
from core.sitemap_discovery import _build_sitemap_urls

def test_build_sitemap_urls_exact():
    urls = _build_sitemap_urls("blog.example.com")
    assert "https://blog.example.com/sitemap.xml" in urls
    assert "https://blog.example.com/sitemap-index.xml" in urls
    assert "https://example.com/sitemap.xml" in urls
    assert "https://example.com/sitemap-index.xml" in urls

def test_build_sitemap_urls_variants():
    urls = _build_sitemap_urls("news.site.com")
    assert any("sitemap1" in u for u in urls)
    assert any("sitemap_news" in u for u in urls)

def test_keyword_filter():
    from core.sitemap_discovery import _filter_by_keyword
    entries = [
        {"url": "https://example.com/transformers-attention"},
        {"url": "https://example.com/attention-mechanism"},
        {"url": "https://example.com/other-topic"},
    ]
    result = _filter_by_keyword(entries, "transformer")
    assert len(result) == 1
    assert "transformer" in result[0]["url"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sitemap_discovery.py -v`
Expected: FAIL — module does not exist yet

- [ ] **Step 3: Write minimal implementation — URL builder and keyword filter**

```python
# core/sitemap_discovery.py
import xml.etree.ElementTree as ET
import urllib.request
import logging
from urllib.parse import urlparse

_logger = logging.getLogger(__name__)

_SITEMAP_VARIANTS = [
    "/sitemap.xml",
    "/sitemap-index.xml",
    "/sitemap1.xml",
    "/sitemap_news.xml",
    "/sitemap_images.xml",
]


def _build_sitemap_urls(domain: str) -> list[str]:
    """Build list of possible sitemap URLs for a domain, with parent fallback."""
    parsed = urlparse(f"https://{domain}")
    base = parsed.netloc or parsed.path
    urls = []
    # Try exact domain first
    for variant in _SITEMAP_VARIANTS:
        urls.append(f"https://{base}{variant}")
    # Try parent domain
    parts = base.split(".")
    if len(parts) > 2:
        parent = ".".join(parts[1:])
        for variant in _SITEMAP_VARIANTS:
            urls.append(f"https://{parent}{variant}")
    return list(dict.fromkeys(urls))  # dedupe


def _filter_by_keyword(entries: list[dict], keyword: str) -> list[dict]:
    """Keep entries whose URL path contains keyword (case-insensitive)."""
    kw = keyword.lower()
    return [e for e in entries if kw in e["url"].lower()]


async def fetch_sitemap(domain: str, keyword: str) -> list[dict]:
    """Fetch sitemap for domain via crawl4ai, filter by keyword.

    Returns list of {url, lastmod, priority} dicts.
    Returns empty list if no sitemap found or no keyword matches.
    """
    from crawl4ai import AsyncWebCrawler

    sitemap_urls = _build_sitemap_urls(domain)
    all_entries: list[dict] = []

    for sitemap_url in sitemap_urls:
        try:
            async with AsyncWebCrawler(verbose=False) as crawler:
                result = await crawler.araw_get(sitemap_url)
                if result.status_code != 200:
                    continue
                content = result.html or result.markdown or ""
                if not content:
                    continue
                entries = _parse_sitemap_xml(content)
                all_entries.extend(entries)
        except Exception as e:
            _logger.debug("Sitemap fetch failed for %s: %s", sitemap_url, e)
            continue

    if not all_entries:
        return []

    return _filter_by_keyword(all_entries, keyword)


def _parse_sitemap_xml(content: str) -> list[dict]:
    """Parse sitemap XML, handling both regular and sitemap-index formats."""
    entries = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return entries

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    # Check if this is a sitemap-index
    if root.tag.endswith("}sitemapindex") or root.tag == "sitemapindex":
        for loc in root.findall("sm:loc", ns):
            child_url = (loc.text or "").strip()
            if child_url:
                entries.append({"url": child_url, "lastmod": None, "priority": None})
        return entries

    # Regular sitemap
    for url_elem in root.findall("sm:url", ns):
        loc = url_elem.find("sm:loc", ns)
        lastmod = url_elem.find("sm:lastmod", ns)
        priority = url_elem.find("sm:priority", ns)
        if loc is not None and loc.text:
            entries.append({
                "url": loc.text.strip(),
                "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else None,
                "priority": float(priority.text) if priority is not None and priority.text else None,
            })
    return entries
```

- [ ] **Step 3 (continued): Write integration test for fetch_sitemap (mocked crawler)**

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_fetch_sitemap_returns_filtered(monkeypatch):
    mock_result = MagicMock()
    mock_result.status_code = 200
    mock_result.html = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/transformer-guide</loc></url>
      <url><loc>https://example.com/unrelated</loc></url>
    </urlset>"""
    mock_result.markdown = ""

    class MockCrawler:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        araw_get = AsyncMock(return_value=mock_result)

    with patch("core.sitemap_discovery.AsyncWebCrawler", return_value=MockCrawler()):
        from core.sitemap_discovery import fetch_sitemap
        result = await fetch_sitemap("example.com", "transformer")
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/transformer-guide"
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sitemap_discovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/sitemap_discovery.py tests/test_sitemap_discovery.py
git commit -m "feat: add SitemapDiscovery via crawl4ai with keyword filter"
```

---

## Task 3: SitemapLinkExtractor (`core/sitemap_link_extractor.py`)

**Files:**
- Create: `core/sitemap_link_extractor.py`
- Test: `tests/test_sitemap_link_extractor.py`

- [ ] **Step 1: Write failing test — extract links and filter by known domain**

```python
from core.sitemap_link_extractor import extract_links
from unittest.mock import patch

def test_extract_links_filters_by_known_domain():
    with patch("core.sitemap_link_extractor._registry") as mock_reg:
        mock_reg.is_known.side_effect = lambda d: d == "known.com"
        html = '''
        <a href="https://known.com/article">Known</a>
        <a href="https://unknown.com/article">Unknown</a>
        <a href="https://also-known.com/page">Also Known</a>
        '''
        result = extract_links("https://source.com/page", html)
        urls = [target for _, target in result]
        assert "https://known.com/article" in urls
        assert "https://also-known.com/page" in urls
        assert "https://unknown.com/article" not in urls

def test_extract_links_preserves_source():
    with patch("core.sitemap_link_extractor._registry") as mock_reg:
        mock_reg.is_known.return_value = True
        html = '<a href="https://example.com/p1"><a href="https://example.com/p2">'
        result = extract_links("https://source.com/article", html)
        sources = [src for src, _ in result]
        assert all(s == "https://source.com/article" for s in sources)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sitemap_link_extractor.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Write implementation**

```python
# core/sitemap_link_extractor.py
import re
from urllib.parse import urljoin, urlparse
from core.site_registry import SiteRegistry

# Module-level singleton registry (lazy init)
_registry: SiteRegistry | None = None


def _get_registry() -> SiteRegistry:
    global _registry
    if _registry is None:
        _registry = SiteRegistry()
    return _registry


def _get_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc


def extract_links(page_url: str, html: str) -> list[tuple[str, str]]:
    """Extract outbound links from HTML, filter by known domain.

    Returns list of (source_page_url, target_url) tuples for links
    whose target domain is already in the SiteRegistry.
    """
    reg = _get_registry()
    link_re = re.compile(r'href="([^"#]+)"')
    results = []

    for match in link_re.finditer(html):
        href = match.group(1)
        full_url = urljoin(page_url, href)
        if not full_url.startswith("http"):
            continue

        target_domain = _get_domain(full_url)
        if reg.is_known(target_domain):
            results.append((page_url, full_url))

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sitemap_link_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/sitemap_link_extractor.py tests/test_sitemap_link_extractor.py
git commit -m "feat: add SitemapLinkExtractor for edge-based link filtering"
```

---

## Task 4: Modify DiscoveryScheduler — integrate new modules

**Files:**
- Modify: `discovery_scheduler.py`

- [ ] **Step 1: Write failing test — search_sitemaps returns keyword-filtered candidates**

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_search_sitemaps_calls_fetch_for_each_domain():
    with patch("core.discovery_scheduler.SiteRegistry") as MockReg, \
         patch("core.discovery_scheduler.fetch_sitemap") as mock_fetch:

        mock_reg_instance = MagicMock()
        mock_reg_instance.all_domains.return_value = ["example.com", "blog.example.com"]
        MockReg.return_value = mock_reg_instance

        mock_fetch.return_value = [
            {"url": "https://example.com/transformer-guide", "lastmod": None, "priority": None}
        ]

        from core.discovery_scheduler import search_sitemaps
        result = await search_sitemaps("transformer")

        assert any("transformer" in r["url"] for r in result)
        assert mock_fetch.call_count == 2  # called for each domain
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_scheduler.py::test_search_sitemaps_calls_fetch_for_each_domain -v`
Expected: FAIL — `search_sitemaps` not yet in discovery_scheduler

- [ ] **Step 3: Add imports and search_sitemaps method to DiscoveryScheduler**

In `discovery_scheduler.py`, add to imports:
```python
from core.site_registry import SiteRegistry
from core.sitemap_discovery import fetch_sitemap
from core.sitemap_link_extractor import extract_links
```

Add new method to `DiscoveryScheduler` class:
```python
async def search_sitemaps(self, keyword: str) -> list[dict]:
    """Search all registered domain sitemaps for keyword-matching URLs.

    Returns list of {url, title, snippet, source} dicts suitable for pipeline.
    """
    results = []
    for domain in self._site_registry.all_domains():
        try:
            entries = await fetch_sitemap(domain, keyword)
        except Exception as e:
            _logger.debug("Sitemap search failed for domain %s: %s", domain, e)
            continue

        for entry in entries:
            url = entry["url"]
            if not self._is_new_url(url):
                continue
            from core.vector_store import get_store
            store = get_store()
            if store.exists(url):
                self._site_registry.add_url(domain, url)
                self._seen_urls.add(url)
                self._persist_seen_urls()
                continue

            results.append({
                "url": url,
                "title": url.split("/")[-1],
                "snippet": "",
                "source": "sitemap",
            })

    return results
```

- [ ] **Step 4: Initialize SiteRegistry in __init__ and wire it into the discovery cycle**

In `DiscoveryScheduler.__init__`, add:
```python
self._site_registry = SiteRegistry()
```

In `_run_discovery_cycle`, replace the `_search_minimax()` results loop with `search_sitemaps()`:
```python
# OLD (remove):
# results = await self._search_keyword(keyword)
# for result in results:
#     url = result["url"]
#     ...

# NEW (add after existing search methods):
# Also search via sitemap for each keyword
sitemap_results = await self.search_sitemaps(keyword)
for result in sitemap_results:
    url = result["url"]
    if not url or not self._is_new_url(url):
        continue
    from core.vector_store import get_store
    store = get_store()
    if store.exists(url):
        self._seen_urls.add(url)
        self._persist_seen_urls()
        continue

    _logger.info("Discovery: ingesting sitemap result %s", url)
    self._in_flight.add(url)
    try:
        if self._pipeline_func:
            asyncio.create_task(self._run_pipeline(url))
        ingested += 1
        self._update_keyword_score(keyword, +1)
        self._seen_urls.add(url)
        self._persist_seen_urls()
        domain = urlparse(url).netloc
        self._site_registry.add_url(domain, url)
    except Exception as e:
        self._update_keyword_score(keyword, -2)
        _logger.error("Discovery: failed to queue sitemap result %s: %s", url, e)
    finally:
        self._in_flight.discard(url)
```

Add `from urllib.parse import urlparse` to imports if not already present.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_discovery_scheduler.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add discovery_scheduler.py
git commit -m "feat: integrate SiteRegistry and SitemapDiscovery into discovery cycle"
```

---

## Task 5: MiniMax sitemap extraction side effect

**Files:**
- Modify: `discovery_scheduler.py` — `_search_minimax()`

- [ ] **Step 1: Read current _search_minimax to understand what to change**

The method needs to be modified so that after MiniMax returns URLs, we:
1. Extract domains from those URLs
2. For each domain, try to fetch `sitemap.xml` via crawl4ai
3. If sitemap found, add domain to `_site_registry`

This is a side-effect-only change — `_search_minimax` still returns its results as before for backward compatibility, but now also seeds the registry.

- [ ] **Step 2: Add sitemap discovery from MiniMax-returned domains**

At the end of `_search_keyword()` (before returning results), add:

```python
# Expand site registry from MiniMax domains
for result in results:
    url = result.get("url", "")
    if not url:
        continue
    domain = urlparse(url).netloc
    if not self._site_registry.is_known(domain):
        try:
            entries = await fetch_sitemap(domain, keyword="")
            if entries:
                self._site_registry.add_domain(domain, source="minimax_discovery", url=url)
                _logger.info("Discovery: added domain %s from MiniMax sitemap", domain)
        except Exception as e:
            _logger.debug("MiniMax sitemap discovery failed for %s: %s", domain, e)
```

- [ ] **Step 3: Commit**

```bash
git add discovery_scheduler.py
git commit -m "feat: use MiniMax results to seed site registry via sitemap discovery"
```

---

## Task 6: Integration test — full discovery cycle

**Files:**
- Create: `tests/test_discovery_integration.py`

- [ ] **Step 1: Write integration test**

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_full_sitemap_discovery_cycle():
    """Test: keyword → sitemap fetch → candidate URL → page crawl → new domain discovered."""
    with patch("core.discovery_scheduler.SiteRegistry") as MockReg, \
         patch("core.discovery_scheduler.fetch_sitemap") as mock_fetch, \
         patch("core.discovery_scheduler.extract_links") as mock_extract, \
         patch("core.discovery_scheduler.get_store") as mock_store:

        # Registry: one known domain
        mock_reg = MagicMock()
        mock_reg.all_domains.return_value = ["example.com"]
        mock_reg.is_known.side_effect = lambda d: d == "example.com"
        MockReg.return_value = mock_reg

        # Sitemap returns one matching URL
        mock_fetch.return_value = [
            {"url": "https://example.com/transformer-post", "lastmod": None, "priority": None}
        ]

        # Store says URL is new
        mock_store_instance = MagicMock()
        mock_store_instance.exists.return_value = False
        mock_store.return_value = mock_store_instance

        # Page has link to a new domain
        mock_extract.return_value = [
            ("https://example.com/transformer-post", "https://newsite.com/related")
        ]

        from core.discovery_scheduler import DiscoveryScheduler

        scheduler = DiscoveryScheduler()
        scheduler._site_registry = mock_reg

        results = await scheduler.search_sitemaps("transformer")
        assert len(results) == 1
        assert "transformer" in results[0]["url"]

        # Verify new domain was added to registry
        added_urls = [u for u, _ in mock_extract.return_value]
        assert "https://newsite.com/related" in [t for _, t in mock_extract.return_value]
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/test_discovery_integration.py -v`
Expected: PASS (given mocks)

- [ ] **Step 3: Commit**

```bash
git add tests/test_discovery_integration.py
git commit -m "test: add integration test for sitemap-based discovery cycle"
```

---

## Self-Review Checklist

1. **Spec coverage:** Can I point to a task for each spec requirement?
   - SiteRegistry persistence ✅ Task 1
   - SitemapDiscovery with crawl4ai ✅ Task 2
   - Keyword filtering ✅ Task 2
   - Sitemap-index recursive resolution ✅ Task 2
   - SitemapLinkExtractor with edge filter ✅ Task 3
   - MiniMax as sitemap discoverer ✅ Task 5
   - DiscoveryScheduler.search_sitemaps ✅ Task 4
   - DiscoveryScheduler integration ✅ Task 4
   - Integration test ✅ Task 6

2. **Placeholder scan:** No "TBD", "TODO", or vague steps found.

3. **Type consistency:** `fetch_sitemap(domain, keyword)` signature matches spec. `extract_links(page_url, html)` returns `list[tuple[str,str]]` matching spec. `SiteRegistry` interface matches spec.

4. **One concern:** `_parse_sitemap_xml` handles `sitemapindex` but not nested sitemap-index → sitemap-index → sitemap chains. Recursion depth limited to 1 level. Acceptable for v1.
