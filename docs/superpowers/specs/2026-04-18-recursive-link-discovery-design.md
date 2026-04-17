# Recursive Link Discovery — Design Spec

## Goal

When crawling any page (category, article, or sitemap), extract ALL outbound links. Follow only those pointing to domains already in our interest graph — bounded recursive discovery.

## Problem

Current desprebursa crawl:
1. Sitemap → get article URLs
2. Category page → extract article links
3. Ingest article URLs
4. **Stop** — no further link extraction

Articles are ingested but their outbound links are never explored.

## Solution

Add link extraction to every crawl. For each outbound link:
1. Parse domain
2. If domain in interest graph → add to registry → try sitemap → crawl recursively
3. If domain NOT in graph → discard

**Bounded recursion**: we only follow links to domains we already have keywords about. Discovery expands web presence of existing interests, doesn't branch into unrelated topics.

## Module: LinkExtractor

**Responsibility:** Extract outbound links from any HTML page.

**Interface:**
- `extract_links(html: str, base_url: str) -> list[str]` — return absolute URLs

**Dependencies:** None (regex-based)

## Module: InterestDomainMatcher

**Responsibility:** Check if a domain matches any interest keyword.

**Interface:**
- `is_interest_domain(domain: str) -> bool` — true if domain is in graph
- `get_interest_domains() -> set[str]` — all domains from graph

**Dependencies:** `core.graph_interests`

## Data Flow

```
Crawl page → extract_markdown → extract_links(html, url)
     │
     ▼
For each outbound URL:
  domain = parse_domain(url)
  if is_interest_domain(domain):
      add_domain_to_registry(domain)
      try fetch sitemap → candidate URLs
      for each candidate: ingest + recursive link extraction
  else: discard
```

## Changes to _search_desprebursa

1. After crawling article URL (via `_fetch_article_snippet`), also extract links
2. Pass extracted links to new link-filtering logic
3. Ingest new URLs and recurse

## Changes to _run_discovery_cycle

1. After `_run_pipeline(url)` completes, extract links from the crawled page
2. Filter links through interest domain matcher
3. Add matching domains to registry
4. Queue their sitemaps for discovery

## Module: DiscoveryLinkExtractor

**Responsibility:** Extract links from crawled pages and route interest-domain links to sitemap discovery.

**Interface:**
- `process_page_links(url: str, html: str, scheduler: DiscoveryScheduler)` — extract links, filter by interest, enqueue new domains

**Dependencies:** `LinkExtractor`, `InterestDomainMatcher`, `SiteRegistry`
