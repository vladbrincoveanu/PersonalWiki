# Discovery Sitemap Pipeline Fix — Design Spec

## Goal

When discovery finds URLs via sitemaps (from link extraction or direct sitemap crawl), those URLs must be ingested into the vault — not just marked as "seen" and forgotten. The discovery cycle must drain both keyword-search results AND enqueued sitemap URLs, subject to the same rate limit.

## Problem

`_enqueue_interest_domain` (discovery_scheduler.py:292-309) fetches sitemap URLs and adds them to `_seen_urls`, but they are never piped through the ingestion pipeline. The discovery cycle only pipelines URLs from arXiv/HN/MiniMax/DespreBursa keyword searches. Sitemap URLs discovered via link extraction sit in `_seen_urls` forever.

**Consequence**: you get "discovery: enqueued interest domain X" log lines but no new notes appear in the vault.

## Solution

Add a sitemap discovery queue to `DiscoveryScheduler`. When `_enqueue_interest_domain` finds sitemap URLs, they go into a queue rather than directly to `_seen_urls`. The queue is drained in `_run_discovery_cycle` alongside keyword search results, subject to `MAX_URLS_PER_CYCLE`.

### Data Flow

```
Discovery cycle:
  for each keyword:
    search arXiv, HN, MiniMax, DespreBursa → candidate URLs
    pipeline candidates (up to MAX_URLS_PER_CYCLE)

  drain sitemap queue (up to MAX_URLS_PER_CYCLE):
    for each enqueued sitemap URL:
      if new → pipeline it
      extract links → InterestDomainMatcher → _enqueue_interest_domain
```

### Queue Design

```python
class DiscoveryScheduler:
    def __init__(self):
        ...
        self._sitemap_queue: asyncio.Queue[str] = asyncio.Queue()
        self._interest_domains: set[str] = set()
```

- `_enqueue_interest_domain`: fetches sitemap, pushes URLs to `_sitemap_queue` (not `_seen_urls`)
- `_run_discovery_cycle`: drains queue alongside keyword results
- Queue items are URLs, not domains — we discovered URLs via sitemap, pipeline them directly
- `_seen_urls` still used for dedup across both sources (keyword + sitemap)

### Changes to `_enqueue_interest_domain`

Before:
```python
def _enqueue_interest_domain(self, domain: str) -> None:
    if domain in self._interest_domains:
        return
    self._interest_domains.add(domain)
    sitemap_urls = self._try_sitemap(domain)
    for url in sitemap_urls:
        if self._is_new_url(url):
            self._seen_urls.add(url)  # stored but never ingested
```

After:
```python
def _enqueue_interest_domain(self, domain: str) -> None:
    if domain in self._interest_domains:
        return
    self._interest_domains.add(domain)
    sitemap_urls = self._try_sitemap(domain)
    for url in sitemap_urls:
        if self._is_new_url(url):
            self._sitemap_queue.put_nowait(url)  # pipeline candidates
```

### Changes to `_run_discovery_cycle`

Two-phase drain within the existing cycle:

```python
async def _run_discovery_cycle(self):
    store = get_store()
    ingested = 0
    seen_this_cycle: set[str] = set()  # local dedup within cycle

    # Phase 1: keyword searches (existing behavior)
    for keyword in self._keywords:
        if ingested >= MAX_URLS_PER_CYCLE:
            break
        results = await self._search_keyword(keyword)
        for result in results:
            url = result["url"]
            if not url or url in seen_this_cycle or store.exists(url):
                continue
            seen_this_cycle.add(url)
            await self._run_pipeline(url)
            ingested += 1
            self._update_keyword_score(keyword, +1)
            self._seen_urls.add(url)

    # Phase 2: drain sitemap queue (new)
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
```

### Persistence

`_sitemap_queue` is not persisted — it's in-memory only. On restart, the next cycle will re-discover domains via link extraction and re-enqueue their sitemaps. This is acceptable since domains accumulate in `_interest_domains` and the disk cache of `_seen_urls` prevents immediate re-ingestion.

`_seen_urls` is still persisted after the cycle (unchanged).

### Deduplication Layers

1. `seen_this_cycle` — local to one cycle, prevents double-pipeline within same run
2. `_seen_urls` — persists across restarts, checked via `_is_new_url()`
3. `store.exists(url)` — final check against LanceDB

All three apply to both keyword-sourced and sitemap-sourced URLs equally.

## Module: DiscoveryScheduler (modified)

**Responsibility:** Coordinate keyword-based search and sitemap-based discovery into a unified ingestion cycle.

**Interface:**
- `is_interest_domain_enqueued(domain)` — check if domain already in `_interest_domains`
- `_enqueue_interest_domain(domain)` — fetch sitemap, push URLs to `_sitemap_queue`
- `_run_discovery_cycle()` — drain keyword searches AND sitemap queue, pipeline URLs

**Dependencies:** arXiv API, HN Algolia API, MiniMax API, crawl4ai, pipeline

**Size target:** existing file unchanged in scope, only logic modified

## What This Does NOT Change

- arXiv, HN, MiniMax, DespreBursa search behavior
- `_search_keyword` interface
- `InterestDomainMatcher` or `DiscoveryLinkExtractor` behavior
- Quality gates, gap detection, entity status checking

## Testing

1. **Unit: `_enqueue_interest_domain` pushes to queue not `_seen_urls`** — mock `_try_sitemap`, verify `put_nowait` called with discovered URLs
2. **Unit: `_run_discovery_cycle` drains sitemap queue** — seed queue with known URLs, verify `_run_pipeline` called for each
3. **Unit: rate limit shared across phases** — seed 15 sitemap URLs, `MAX_URLS_PER_CYCLE=10`, verify only 10 pipelines
4. **Integration: sitemap URL appears in vault** — full cycle with mocked search + sitemap, verify note written
5. **Integration: sitemap URL skipped if already in store** — same URL in both keyword results and sitemap queue, verify only one pipeline call
