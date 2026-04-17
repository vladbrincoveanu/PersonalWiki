# Interest-Graph Discovery — Design Spec

## Goal

Replace the unreliable `_search_minimax()` URL discovery with a **crawl4ai-first, interest-graph-filtered** discovery system. Discovery is purely an input expansion for crawl4ai — it gives crawl4ai more URLs to crawl, filtered to topics of interest. The pipeline itself is unchanged.

## Core Insight

The interest graph is the filter, not the source. We don't add new interest nodes — we add **edges** between existing nodes by discovering content that connects them.

## Architecture

```
keyword "transformers"
      │
      ▼
[Site Registry] → fetch sitemap.xml via crawl4ai (with parent-path fallback)
      │
      ▼
Filter sitemap URLs by keyword → candidate URLs
      │
      ▼
crawl4ai crawls each candidate page
      │
      ▼
Extract outbound links → is target domain in interest graph?
      │
      ├── No  → discard
      │
      └── Yes → is domain already in registry?
                  ├── No  → add domain to registry + discover its sitemap.xml
                  └── Yes → skip (already processed)
              │
              ▼
         Pipeline (if URL passes edge filter and not already ingested)
```

### MiniMax's role (reduced)

- **Domain discovery**: MiniMax web search finds pages matching a keyword; we extract the domain and try to fetch its `sitemap.xml` — if successful, add domain to registry.
- **NOT a source of direct URLs** — we no longer use MiniMax-returned URLs for ingestion directly.
- **Sitemap URL extraction**: when MiniMax returns a page URL, also try to find its `sitemap.xml` via `.sitemap.xml` and `sitemap-index.xml` patterns.

### Site Registry

**Stored at**: `~/.personalWiki/site_registry.json`

```json
{
  "domains": {
    "huggingface.co": {
      "added_at": "2026-04-17",
      "source": "manual",       // or "minimax_discovery"
      "last_sitemap_check": "2026-04-17",
      "known_urls": [
        "https://huggingface.co/blog/transformers",
        "https://huggingface.co/docs/transformers"
      ]
    }
  }
}
```

**Registry growth rules:**
1. On manual ingestion: extract domain from URL → add to registry
2. On MiniMax discovery: domain found → try sitemap → if sitemap exists, add to registry
3. On outbound link during crawl: if domain not in registry AND has sitemap → add to registry

### Sitemap Discovery Strategy

When checking `example.com/sitemap.xml`, try in order:
1. `https://blog.example.com/sitemap.xml`
2. `https://blog.example.com/sitemap-index.xml`
3. `https://example.com/sitemap.xml`
4. `https://example.com/sitemap-index.xml`

Also try `sitemap.xml` variants: `/sitemap1.xml`, `/sitemap_news.xml`, `/sitemap_images.xml`.

If sitemap is a `sitemap-index` (points to other sitemaps), recursively resolve all child sitemaps.

### Sitemap Parsing (via crawl4ai)

crawl4ai fetches and parses the sitemap XML. We extract:
- `<loc>` — the URL
- `<lastmod>` — modification date (optional, for freshness)
- `<priority>` — crawl priority (optional, for ordering)

URLs filtered by keyword: keep only URLs where the path/filename contains the keyword (case-insensitive substring match).

### Edge Filter

On crawl4ai page crawl, extract all outbound links (`<a href>`). For each link:
1. Parse target domain
2. If domain is in `domains` (registry) → **passes edge filter**
3. If domain is not in registry but sitemap is discoverable → add to registry → passes edge filter
4. Otherwise → discard

### MiniMax Sitemap Extraction

When `_search_minimax()` returns a URL, also:
1. Try `url/sitemap.xml` and `url/sitemap-index.xml`
2. If either returns 200, extract all `<loc>` entries → add those domains to registry
3. This expands the registry even when MiniMax's direct URLs are not useful

---

## Module: SiteRegistry

**Responsibility:** Persist and query known domains + their discovered URLs.

**Interface:**
- `SiteRegistry.add_domain(domain, source, url)` — register a domain with an originating URL
- `SiteRegistry.add_url(domain, url)` — add a known URL to a domain
- `SiteRegistry.is_known(domain)` → bool
- `SiteRegistry.all_domains()` → list of domains
- `SiteRegistry.known_urls(domain)` → list of URLs

**Dependencies:** `~/.personalWiki/site_registry.json`, `core.graph_interests`

**Size target:** ~150 lines

---

## Module: SitemapDiscovery

**Responsibility:** Fetch and parse sitemaps for a domain via crawl4ai, return keyword-filtered URLs.

**Interface:**
- `fetch_sitemap(domain, keyword)` → list[dict] where dict is `{url, lastmod, priority}`
- Tries multiple sitemap URL patterns (see above)
- Returns empty list if no sitemap found or keyword match is empty

**Dependencies:** crawl4ai `AsyncWebCrawler`

**Size target:** ~100 lines

---

## Module: SitemapLinkExtractor

**Responsibility:** Extract outbound links from a crawled page, filter by whether target domain is already known (edge to existing content), return (source_url, target_url) pairs.

**Interface:**
- `extract_links(page_url, html)` → list[tuple[str, str]] of (source_url, filtered_target_url)

**Dependencies:** `SiteRegistry`, `core.graph_interests`

**Size target:** ~80 lines

---

## Module: DiscoveryScheduler (modified)

**Changes to existing `_search_minimax()`:**
- Remove direct URL return path
- Add sitemap extraction step: for each URL MiniMax returns, try to fetch its `sitemap.xml`
- If sitemap found → add domain to `SiteRegistry`
- Return nothing (MiniMax no longer drives ingestion URLs directly)

**New method:**
- `search_sitemaps(keyword)` — iterates all registered domains, fetches their sitemaps via crawl4ai, filters by keyword, returns candidate URLs for pipeline

**Changes to `_run_discovery_cycle()`:**
- Replace `_search_minimax()` call in the keyword loop with `search_sitemaps(keyword)`
- After each successful crawl, call `SitemapLinkExtractor` on the page → potentially expand registry

---

## Changes to Existing Code

### `discovery_scheduler.py`
- Remove `_search_minimax()` URL-returning logic (keep domain-extraction side effect)
- Add `SiteRegistry` import and instantiation
- Add `search_sitemaps()` coroutine
- Add `SitemapDiscovery` usage in `_run_discovery_cycle()`

### New file: `core/site_registry.py`
- `SiteRegistry` class as described above
- Persists to `~/.personalWiki/site_registry.json`
- Auto-creates parent dir on first write

### New file: `core/sitemap_discovery.py`
- `fetch_sitemap()` function
- Handles sitemap-index recursive resolution
- Keyword filtering on URL paths

### New file: `core/sitemap_link_extractor.py`
- `extract_links()` function
- Interest graph domain lookup

### `core/graph_interests.py`
- Add `is_domain_in_graph(domain)` — check if domain or parent domain appears in any interest keyword or known URL slug

---

## Error Handling

- Sitemap fetch fails → log warning, skip domain, don't remove from registry
- No keyword matches in sitemap → return empty, don't treat as error
- crawl4ai crawl fails for a candidate URL → skip, log
- Registry write fails → log error, continue (in-memory stays correct for this cycle)
- Circular domain addition (A links to B, B links back to A) → `is_known()` prevents infinite expansion within same cycle

---

## Testing

1. **Unit: SiteRegistry** — add, query, persist, load
2. **Unit: SitemapDiscovery** — sitemap parsing, keyword filter, sitemap-index recursion
3. **Unit: SitemapLinkExtractor** — link extraction, edge filter logic
4. **Integration: full cycle** — keyword → sitemap fetch → candidate URLs → page crawl → new domain discovered → sitemap fetched → pipeline triggered

---

## What This Replaces

`_search_minimax()` no longer returns direct ingestion candidates. The MiniMax web search tool is demoted to a domain-discovery signal only — it helps us find sitemaps, not URLs.

The `search_hn`, `search_arxiv`, `search_desprebursa` methods are unchanged — they use real APIs and work correctly.
