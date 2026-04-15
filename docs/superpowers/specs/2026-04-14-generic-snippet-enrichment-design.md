# Generic Snippet Enrichment for Discovery Scheduler

## Problem

Discovery scheduler search sources return URLs with empty snippets. The pipeline then has to re-fetch those URLs to get actual content. Additionally, sitemap-based website discovery has no "skip subpages if sitemap is sufficient" logic — it always crawls category pages even when unnecessary.

## General Pattern

### 1. Post-fetch snippet enrichment (all sources)

After all searches return, any result with an empty snippet gets its article fetched concurrently. A generic `_enrich_snippets()` method handles all sources uniformly.

```python
async def _enrich_snippets(self, results: list[dict]) -> list[dict]:
    """
    For any result with an empty snippet, fetch the article and extract one.
    Works for any source — desprebursa, generic URLs, etc.
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
```

In `_search_keyword`, after all 4 searches return and are merged:

```python
# After: results = arxiv + hn + minimax + desprebursa
results = await self._enrich_snippets(results)
```

This replaces per-source snippet logic — desprebursa, and any future source, all get enriched the same way.

### 2. Generic article snippet extraction

```python
async def _fetch_article_snippet(self, url: str) -> str:
    """Fetch article page and extract first meaningful paragraph as snippet."""
    try:
        text = await extract_url(url)
        # Extract first paragraph over 80 chars
        for para in text.split("\n\n"):
            para = para.strip()
            if len(para) > 80:
                return para[:200]
        return ""
    except Exception:
        return ""
```

### 3. Sitemap-first optimization (all websites)

For any website discovery that uses a sitemap as Tier 1:
- If sitemap returns ≥ `limit` results, skip Tier 2 (subpage/category crawling) entirely
- Only fall to Tier 2 if sitemap returned fewer than `limit`

This applies to desprebursa and any future website-based source that follows the same sitemap→subpages pattern.

## Changes

| File | Change |
|------|--------|
| `core/discovery_scheduler.py` | Add `_enrich_snippets()` generic post-processing; call after all searches merge in `_search_keyword`; keep desprebursa Tier 2 skip logic |

## Behavior

- **arxiv, HN, MiniMax** — already return real snippets → `_enrich_snippets` is no-op for them
- **DespreBursa** — returns empty snippets → enriched concurrently after search returns
- **Future website sources** — same: empty snippet → enriched automatically
- **Sitemap skip** — desprebursa (and any future sitemap-based source) skips Tier 2 when Tier 1 already returned ≥5 results
