# Depth Drill & Thin Page Detection Design

**Date:** 2026-04-15
**Status:** Design
**Type:** Bug fix + feature

## Problem Statement

Two bugs in `core/discovery_scheduler.py`:

1. **`_search_minimax` not awaited** (line 202) — `async def` method called without `await`, results silently discarded, RuntimeWarning on every call.
2. **Thin page ingestion** — discovered URLs that are listing/category pages (e.g., `/categorii-publicatii/bvb`) are accepted as results. The system repeatedly crawls these pages every cycle without ever finding actual article content. No drill-down exists to find the actual articles beneath listing pages.

---

## Bug Fix 1: Unawaited Coroutine

**File:** `core/discovery_scheduler.py`, line 202

```python
# Before (broken):
results.extend(self._search_minimax(keyword))

# After (fixed):
results.extend(await self._search_minimax(keyword))
```

This is a one-word fix. No design required.

---

## Feature: Generic Depth Drill

### Principle

When a discovered URL yields thin content (listing page, nav-heavy, no real article), drill up to 5 levels deeper to find actual content. Works generically for any website — not just DespreBursa.

### Detection: What Makes a Page "Thin"?

A page is **thin** if BOTH conditions are true:

| Condition | Threshold | Why |
|-----------|-----------|-----|
| Prose char count | < 500 chars | Almost no readable text |
| Prose ratio | < 30% prose | Nav/header/layout dominates |

**Prose detection heuristic:** Split text by double newlines into blocks. A block is prose if it: has >3 words, contains lowercase letters, is not all-caps, has sentence punctuation (`.` `!` `?`). Count prose chars / total chars.

If either threshold fails, the page is "not thin" — use it as-is.

### Drill-Down State Machine

```
URL → Fetch (Crawl4AI) → Quality Check
                           ↓
              Not thin? → ✅ Return result with snippet
                           ↓ yes
              Thin? → Extract article links → Pick best → Drill level+1
                                                          ↓
                                              Max depth (5)? → ⛔ Stop, return thin
                                              Article found? → ✅ Return
```

**Stop conditions:**
- Depth ≥ 5 reached
- No article links found on page
- Valid content found (passes thin check)

### Link Extraction

From the HTML of a thin page, extract up to 10 candidate article links:

**Include if ALL true:**
- Same domain as parent URL
- Not a nav/footer/header/sidebar link (skip URLs containing `/nav/`, `/menu/`, `/footer/`, `/header/`, `/sidebar/`, `/tag/`)
- Not pagination (`?page=`, `/page/`, `/page2/`, `/p2/`)
- Not a media file (`.jpg`, `.png`, `.pdf`, `.mp4`, `.zip`)
- Article-like: URL contains `/article/`, `/post/`, `/news/`, `/blog/`, or a year pattern (`/2024/`, `/2025/`, `/2026/`)

**Sort candidates by priority:**
1. Keyword in URL text/path (best match)
2. Longest URL slug (most specific article)
3. DOM order (first article link found)

Pick top 1 for drill-down.

### Architecture: Where Does Drill-Down Live?

**Option 3 (both):**

1. **Primary: `_fetch_article_snippet`** — internally detects thin content and drills. Returns final rich result. Callers (all sources) transparently get drill behavior.

2. **Safety net: `_search_keyword` post-pass** — after all 4 sources return, any URL that still has an empty snippet gets one final drill attempt via `_fetch_article_snippet`. Catches sources that bypass the direct call.

### Implementation: New Function — `_fetch_with_drill`

A new async function `_fetch_with_drill(url: str, keyword: str, depth: int = 0) -> str` that:
1. Calls `extract_url(url)` via Crawl4AI
2. Measures prose count and ratio
3. If not thin: return the first paragraph (>80 chars) as snippet
4. If thin and depth < 5: extract article links, pick best, recurse
5. If thin and depth ≥ 5: return empty string

```python
async def _fetch_with_drill(url: str, keyword: str, depth: int = 0) -> str:
    """Fetch URL, drill if thin. Returns snippet text or empty string."""
    MAX_DEPTH = 5
    MIN_PROSE_CHARS = 500
    MIN_PROSE_RATIO = 0.30

    try:
        text = await extract_url(url)
    except Exception:
        return ""

    prose_chars, prose_ratio = _measure_prose(text)
    is_thin = (prose_chars < MIN_PROSE_CHARS) or (prose_ratio < MIN_PROSE_RATIO)

    if not is_thin:
        # Extract first meaningful paragraph
        for para in text.split("\n\n"):
            if len(para.strip()) > 80:
                return para.strip()[:200]

    # Thin — try to drill
    if depth >= MAX_DEPTH:
        return ""  # Give up

    candidates = _extract_article_links(text, url, keyword)
    if not candidates:
        return ""

    # Pick best: keyword match > longest slug > first
    best = _pick_best_link(candidates, keyword)
    return await _fetch_with_drill(best, keyword, depth + 1)
```

### Link Extraction Helper

```python
def _extract_article_links(html: str, parent_url: str, keyword: str) -> list[str]:
    """Extract candidate article links from HTML of a thin page."""
    from urllib.parse import urljoin, urlparse

    SKIP_PATTERNS = ["/nav/", "/menu/", "/footer/", "/header/",
                     "/sidebar/", "/pagination/", "/tag/", "/category/"]
    MEDIA_EXTS = [".jpg", ".png", ".gif", ".pdf", ".mp4", ".zip"]
    ARTICLE_INDICATORS = ["/article/", "/post/", "/news/", "/blog/",
                         "/2024/", "/2025/", "/2026/"]

    parsed_parent = urlparse(parent_url)
    domain = parsed_parent.netloc

    link_re = re.compile(r'href="([^"#]+)"')
    candidates = []

    for match in link_re.finditer(html):
        href = match.group(1)
        full_url = urljoin(parent_url, href)
        parsed = urlparse(full_url)

        # Same domain only
        if parsed.netloc != domain:
            continue

        url_lower = full_url.lower()

        # Skip nav/footer patterns
        if any(p in url_lower for p in SKIP_PATTERNS):
            continue

        # Skip media
        if any(url_lower.endswith(ext) for ext in MEDIA_EXTS):
            continue

        # Must look like an article
        if not any(ind in url_lower for ind in ARTICLE_INDICATORS):
            continue

        candidates.append(full_url)

    return list(dict.fromkeys(candidates))  # dedupe, preserve order
```

### Link Picker

```python
def _pick_best_link(urls: list[str], keyword: str) -> str:
    """Pick best article link from candidates."""
    if not urls:
        return ""

    keyword_lower = keyword.lower()

    # Score each URL
    scored = []
    for url in urls:
        score = 0
        url_lower = url.lower()
        # Keyword match
        if keyword_lower in url_lower:
            score += 10
        # Slug length (longer = more specific article)
        slug = url_lower.split("/")[-1]
        score += len(slug) / 100
        scored.append((score, url))

    scored.sort(reverse=True)
    return scored[0][1]
```

### Prose Measurer

```python
def _measure_prose(text: str) -> tuple[int, float]:
    """Return (prose_char_count, prose_ratio) for text."""
    import re
    total_chars = len(text.strip())
    if total_chars == 0:
        return 0, 0.0

    blocks = re.split(r'\n\s*\n', text.strip())
    prose_chars = 0

    for block in blocks:
        block = block.strip()
        words = block.split()
        if len(words) < 3:
            continue
        # Skip all-caps blocks (headings, nav)
        if block.isupper():
            continue
        # Skip blocks with mostly symbols (tables, data)
        alpha = sum(1 for c in block if c.isalpha())
        if alpha / len(block) < 0.3:
            continue
        prose_chars += len(block)

    ratio = prose_chars / total_chars if total_chars > 0 else 0.0
    return prose_chars, ratio
```

### Changes to Existing Code

1. **Line 202:** Add `await` before `self._search_minimax(keyword)`
2. **`_fetch_article_snippet`**: Refactor to call `_fetch_with_drill` internally
3. **`_search_keyword` post-pass**: After `await self._enrich_snippets(results)`, for any result with empty snippet, call `_fetch_with_drill(result["url"], keyword)` as a final attempt

### Test Cases

| Case | URL | Content | Expected |
|------|-----|---------|----------|
| Direct article | `https://example.com/article/123` | 2000 chars prose, 60% ratio | Returns snippet, no drill |
| Listing page | `https://desprebursa.ro/categorii-publicatii/bvb` | 200 chars, 10% ratio | Drill → finds article URL → returns snippet |
| Drill max depth | Listing → listing → listing... | Thin at all 5 levels | Returns empty |
| Pagination page | `?page=2` | Thin but has links | Drill into it |

---

## Summary of Changes

| File | Change |
|------|--------|
| `core/discovery_scheduler.py` | Fix `await` on line 202; refactor `_fetch_article_snippet` to `_fetch_with_drill`; add prose measurer, link extractor, link picker; add post-pass safety net |
| `tests/test_discovery_scheduler.py` | Add tests for depth drill, thin detection, prose measurement, link picker |

---

## No Placeholders

All thresholds, functions, and logic are fully specified above.
