# DespreBursa Site Discovery — Integration Design

**Date:** 2026-04-14
**Goal:** Integrate desprebursa.ro as a discoverable source in the existing autonomous discovery scheduler, so articles matching vault-derived keywords are automatically found and ingested.

## Context

The personalWiki autonomous discovery scheduler (`core/discovery_scheduler.py`) fires discovery cycles based on interest keywords extracted from the vault graph. For each keyword it searches three sources in parallel: arXiv, Hacker News, and MiniMax. The missing piece is **site-specific web discovery** — finding all articles on a given site that match a keyword, not just articles that are the primary result of a web search.

DespreBursa.ro is a Romanian financial news site covering BVB (stock market), companies, macro markets, and strategy. It has category pages (e.g., `/categorii-publicatii/bvb`, `/categorii-publicatii/companii`) and likely a sitemap at `/sitemap.xml`.

## Design

### Architecture

Extend `DiscoveryScheduler` with a new `_search_desprebursa(keyword)` method that:
1. Fetches the sitemap at `https://www.desprebursa.ro/sitemap.xml` (or category page fallback)
2. Extracts all article URLs from `<loc>` tags
3. Filters URLs by the keyword (case-insensitive substring match on the URL path)
4. Returns a list of `{"url": ..., "title": ..., "snippet": "", "source": "desprebursa"}` dicts

The scheduler loop calls `_search_desprebursa` alongside `_search_arxiv`, `_search_hn`, and `_search_minimax` for each keyword. New URLs are deduplicated against LanceDB and the in-memory `_seen_urls` set, then passed to the pipeline via `asyncio.create_task(_run_pipeline(url))`.

### Why not a separate script?

A standalone script would be simpler but wouldn't integrate with the scheduler's deduplication, rate limiting, or pipeline integration. This approach keeps all discovery logic in one place and means desprebursa articles are discovered automatically as part of the ongoing autonomous discovery cycle, not as a one-off manual crawl.

### Components

#### 1. `core/discovery_scheduler.py` — add `_search_desprebursa`

```python
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
        import xml.etree.ElementTree as ET
        req = urllib.request.Request(sitemap_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8")
        root = ET.fromstring(data)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for loc in root.findall("sm:loc", ns):
            url = loc.text.strip() if loc.text else ""
            if url and "desprebursa.ro" in url and url not in seen_urls:
                if keyword.lower() in url.lower():
                    articles.append({"url": url, "title": url.split("/")[-1], "snippet": "", "source": "desprebursa"})
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
        for cat_page in category_pages:
            if len(articles) >= limit:
                break
            try:
                text = await extract_url(cat_page)
                # Extract article links from page content
                import re
                article_links = re.findall(r'href="(https://www\.desprebursa\.ro/[^"#]+)"', text)
                for link in article_links:
                    if link not in seen_urls and keyword.lower() in link.lower():
                        articles.append({"url": link, "title": link.split("/")[-1], "snippet": "", "source": "desprebursa"})
                        seen_urls.add(link)
            except Exception:
                continue
    except Exception as e:
        _logger.warning("DespreBursa category crawl failed: %s", e)

    return articles[:limit]
```

#### 2. Modify `_search_keyword` to call `_search_desprebursa`

In `_search_keyword`, add after the MiniMax search call:

```python
# DespreBursa site search
try:
    results.extend(await self._search_desprebursa(keyword))
except Exception as e:
    _logger.warning("Discovery: DespreBursa search failed for %s: %s", keyword, e)
```

#### 3. Config (already exists)

No new config needed. The existing `DISCOVERY_ENABLED`, `DISCOVERY_INTERVAL`, and `MAX_URLS_PER_CYCLE` control the scheduler behavior. `MAX_URLS_PER_CYCLE` limits total URLs per cycle across all sources.

### Data Flow

```
scheduler loop (per keyword)
    ├── _search_arxiv(keyword) → [{url, title, snippet, source}]
    ├── _search_hn(keyword) → [{url, title, snippet, source}]
    ├── _search_minimax(keyword) → [{url, title, snippet, source}]
    └── _search_desprebursa(keyword) → [{url, title, snippet, source}]
         │
         │  (deduplicated against _seen_urls + LanceDB)
         ↓
    _run_pipeline(url) → ingesters.router.extract(url)
         │
         └── Document(raw_text, content_type, frontmatter) → vault
```

### Error Handling

- **Sitemap unreachable:** Log warning, fall back to category page crawl
- **Category crawl fails:** Log warning, return whatever articles were found so far (empty list is acceptable)
- **Individual article extraction fails:** Caught by existing `extract()` pipeline (newspaper3k → crawl4ai → paywall stub)
- **All desprebursa tiers fail:** Silently continue — other sources still work

### Testing

1. **Unit test: sitemap parsing** — mock `urllib.request.urlopen` to return a sample XML sitemap, verify article URLs are extracted
2. **Unit test: keyword filtering** — mock sitemap with mixed URLs, verify only matching URLs are returned
3. **Unit test: category page fallback** — mock `extract_url` to return HTML with article links, verify extraction
4. **Integration test: full cycle** — verify `_search_desprebursa("BVB")` returns desprebursa URLs without raising

### Scope

This design adds desprebursa discovery as a new search source within the existing scheduler. It does NOT:
- Change the router or existing ingester behavior for single-URL extraction
- Add a manual crawl command
- Modify the app lifespan or pipeline enrichment

These can be pursued separately if needed later.
