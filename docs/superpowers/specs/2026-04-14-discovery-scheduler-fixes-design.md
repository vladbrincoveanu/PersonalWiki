# Discovery Scheduler — Three Fixes

## 1. LLM JSON Parsing Bug

**Problem:** `graph_interests.py` uses `json.loads()` which fails if MiniMax appends any text after the JSON array.

**Fix:** Use `json.JSONDecoder().raw_decode()` which extracts only the first JSON value and ignores trailing text.

```python
# Before (line 104):
validated = json.loads(content)

# After:
decoder = json.JSONDecoder()
validated, _ = decoder.raw_decode(content)  # extracts JSON, ignores trailing text
```

Also strip trailing backticks first:
```python
content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
```

## 2. DespreBursa: Fetch Article Content, Not Just URLs

**Problem:** Search returns URLs with empty snippets. Pipeline then re-fetches the same URL later. Category pages are fetched even when sitemap already found 5+ results.

**Fix A — Skip Tier 2 if Tier 1 has enough results:**

Tier 1 (sitemap) currently searches all URLs even after finding ≥5. The `return` on line 225 only exits the sitemap loop — but Tier 2 still runs because the check on line 230 happens after. Move the Tier 2 check inside Tier 1 so we return early.

**Fix B — Fetch article content during search:**

For each found article URL, fetch it once during search to extract a real snippet. Return the enriched result so the pipeline doesn't need to re-fetch.

```python
async def _fetch_article_snippet(url: str) -> str:
    """Fetch article page and extract first paragraph as snippet."""
    try:
        text = await extract_url(url)
        # Extract first meaningful paragraph
        paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 80]
        return paragraphs[0][:200] if paragraphs else ""
    except Exception:
        return ""
```

During search, after finding matching article URLs, concurrently fetch snippets:

```python
# After finding URLs in sitemap/category
if results:
    snippets = await asyncio.gather(*[self._fetch_article_snippet(r["url"]) for r in results])
    for r, snippet in zip(results, snippets):
        if snippet:
            r["snippet"] = snippet
```

## 3. Persist `_seen_urls`

**Problem:** `_seen_urls` is an in-memory set. On every restart, all previously ingested URLs are re-eligible. The store check prevents re-ingestion but HTTP search requests have already fired.

**Fix:**

(a) **Warm `_seen_urls` from vector store on startup:**

```python
def __init__(self):
    self._running = False
    self._scheduler_task: asyncio.Task | None = None
    self._keywords: list[str] = []
    self._seen_urls: set[str] = set()
    self._in_flight: set[str] = set()
    self._pipeline_func = None

    # Warm seen URLs from vector store
    try:
        from core.vector_store import get_store
        store = get_store()
        self._seen_urls = store.get_all_urls()  # new method on store
    except Exception:
        pass
```

(b) **Add `get_all_urls()` to vector store** — returns all indexed URLs so scheduler knows what's already been ingested.

(c) **Persist to disk between cycles** — save `_seen_urls` to `~/.personalWiki/discovery_seen_urls.json` every cycle and load on startup.

## Summary of Changes

| File | Change |
|------|--------|
| `core/graph_interests.py` | Use `raw_decode()` for LLM JSON parsing |
| `core/discovery_scheduler.py` | Fix Tier 2 skip logic; fetch article snippets; warm `_seen_urls` from store; persist to disk |
| `core/vector_store.py` | Add `get_all_urls()` method |
