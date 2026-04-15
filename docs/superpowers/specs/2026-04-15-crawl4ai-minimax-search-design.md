# Spec: Crawl4AI + Real MiniMax Search

## Problem

1. `_search_minimax()` in `discovery_scheduler.py` is a hallucination machine — it asks the LLM to *invent* URLs, which get hallucinated. Discovery returns fake links that fail to ingest.
2. `ingesters/web.py` uses raw Crawl4AI without content filtering — extracted markdown contains nav bars, cookie banners, footers that pollute snippets and enrichment.

## Solution

### Part 1: Crawl4AI `fit_markdown` upgrade

In `ingesters/web.py`:

```python
from crawl4ai import CrawlerRunConfig

async def extract_url(url: str) -> str:
    config = CrawlerRunConfig(fit_markdown=True)
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=config)
    if not result.success or not result.markdown:
        raise ValueError(f"Failed to extract content from: {url}")
    return str(result.markdown)
```

`fit_markdown=True` removes navigation, footers, cookie banners, and other boilerplate before the LLM sees the text. Works for all sources using `extract_url()` — web ingestion, desprebursa, generic snippet enrichment.

### Part 2: MiniMax function-calling search

Replace `_search_minimax()` with a 2-round hybrid approach.

**Round 1 — Tool call attempt:**

Send a search request with MiniMax's `tools` parameter, using `web_search` as the tool name (confirmed by user as available). The tool definition follows standard OpenAI-style function calling shape: `{"type": "function", "function": {"name": "web_search", "description": "...", "parameters": {...}}}`. If MiniMax returns `tool_calls` with real URLs → proceed to Crawl4AI fetch. If the tool is not enabled or returns no tool_calls → fall through to Round 2.

**Round 2 — Fallback:**

If MiniMax returns no tool calls (tool unavailable or error), fall back to:
- Parse the text response for URLs via regex (`https://...`)
- Crawl4AI fetch each candidate URL
- Extract snippet from the crawled content

**Dedup:** All results checked against `_seen_urls` and `store.exists()` before returning.

**Result shape unchanged:** `[{url, title, snippet, source}]` — 3 results per keyword.

### Code changes

| File | Change |
|------|--------|
| `ingesters/web.py` | Add `CrawlerRunConfig(fit_markdown=True)` to `extract_url()` |
| `core/discovery_scheduler.py` | Replace `_search_minimax()` with hybrid tool-use + Crawl4AI approach |

### Error handling

- MiniMax tool unavailable → fallback to URL extraction from text response
- MiniMax completely fails → log warning, return `[]` (other 3 sources still work)
- Crawl4AI fails on a URL → skip that URL, continue
- All URLs fail → return partial results or empty list

### Testing

1. Call `_search_keyword("reinforcement learning")` and verify 3 real, crawlable URLs returned (not hallucinated)
2. Verify snippets are clean article text, not nav/footer content
3. Run full discovery cycle and verify ingest pipeline accepts the URLs

## Out of scope

- YouTube playlist/channel batch ingestion
- Note format upgrades (frontmatter, gap callouts, key_quotes)
