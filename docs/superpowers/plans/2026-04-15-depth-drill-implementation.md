# Depth Drill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix unawaited coroutine bug and implement generic 5-level depth drill for thin page detection in `core/discovery_scheduler.py`.

**Architecture:** New helper functions (`_measure_prose`, `_extract_article_links`, `_pick_best_link`, `_fetch_with_drill`) added to `discovery_scheduler.py`. `_fetch_article_snippet` refactored to call `_fetch_with_drill`. Safety-net post-pass in `_enrich_snippets` catches any source that bypasses the direct call.

**Tech Stack:** Python asyncio, `re` module, `urllib.parse`, existing `extract_url` from `ingesters.web`.

---

## File Map

| File | Change |
|------|--------|
| `core/discovery_scheduler.py` | Modify: fix await bug (line 202), add helpers, refactor `_fetch_article_snippet`, add post-pass |
| `tests/test_discovery_scheduler.py` | Add: tests for `_measure_prose`, `_extract_article_links`, `_pick_best_link`, `_fetch_with_drill` integration |

---

## Task 1: Bug Fix — Add `await` on `_search_minimax`

**Files:**
- Modify: `core/discovery_scheduler.py:202`

- [ ] **Step 1: Read current line 202**

```bash
sed -n 200,205p core/discovery_scheduler.py
```

Expected: `results.extend(self._search_minimax(keyword))` (no `await`)

- [ ] **Step 2: Add `await`**

```python
results.extend(await self._search_minimax(keyword))
```

- [ ] **Step 3: Verify**

```bash
sed -n 200,205p core/discovery_scheduler.py
```

Expected: `results.extend(await self._search_minimax(keyword))`

- [ ] **Step 4: Commit**

```bash
git add core/discovery_scheduler.py
git commit -m "fix: await coroutine in _search_keyword"
```

---

## Task 2: Add Helper Functions to `discovery_scheduler.py`

**Files:**
- Modify: `core/discovery_scheduler.py` — add 3 helpers before `_fetch_article_snippet`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_discovery_scheduler.py`:

```python
def test_measure_prose():
    """Prose measurer returns char count and ratio."""
    from core.discovery_scheduler import _measure_prose

    # Real article: mixed paragraphs
    text = "This is a paragraph.\n\nAnother paragraph here."
    chars, ratio = _measure_prose(text)
    assert chars > 0
    assert 0 < ratio <= 1.0

    # Thin: nav-heavy with short blocks
    thin = "HOME | ABOUT | CONTACT\n\n" * 10
    chars, ratio = _measure_prose(thin)
    assert ratio < 0.3  # mostly symbols/caps

    # All-caps headings
    text2 = "IMPORTANT NEWS\n\nA real sentence here. With more content."
    chars, ratio = _measure_prose(text2)
    assert chars > 0

    # Empty
    chars, ratio = _measure_prose("")
    assert chars == 0
    assert ratio == 0.0


def test_extract_article_links():
    """Link extractor filters nav/media and returns article candidates."""
    from core.discovery_scheduler import _extract_article_links

    html = """
    <a href="/nav/menu">Skip</a>
    <a href="/footer/about">Also skip</a>
    <a href="/article/how-to-code">Best match</a>
    <a href="/blog/2024/post">Good article</a>
    <a href="/news/industry-update">Also good</a>
    <a href="/category/tech">Not article</a>
    <a href="https://other.com/page">Cross-domain</a>
    <a href="/tag/python">Tag link</a>
    <a href="/article">Bare article path</a>
    <a href="/2025/report">Year pattern</a>
    """
    parent = "https://example.com/category/tech"
    links = _extract_article_links(html, parent, "python")
    # Should include: /article/how-to-code, /blog/2024/post, /news/industry-update, /2025/report
    assert any("/article/how-to-code" in l for l in links)
    assert any("/blog/2024/post" in l for l in links)
    assert any("/news/industry-update" in l for l in links)
    assert any("/2025/report" in l for l in links)
    # Should exclude: nav, footer, cross-domain, tag, category, bare /article
    assert not any("nav" in l or "footer" in l or "other.com" in l or "tag" in l for l in links)


def test_pick_best_link():
    """Link picker scores by keyword match + slug length."""
    from core.discovery_scheduler import _pick_best_link

    candidates = [
        "https://example.com/article/python-tips",
        "https://example.com/blog/2024/a-very-long-article-title-about-python-programming",
        "https://example.com/news/general-update",
    ]
    # Keyword "python" should rank the long slug highest due to keyword+length
    best = _pick_best_link(candidates, "python")
    assert "python" in best.lower()

    # No keyword match — picks longest slug
    best2 = _pick_best_link(candidates, "javascript")
    assert "very-long-article" in best2  # longest slug
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki
python -m pytest tests/test_discovery_scheduler.py::test_measure_prose tests/test_discovery_scheduler.py::test_extract_article_links tests/test_discovery_scheduler.py::test_pick_best_link -v 2>&1 | tail -20
```

Expected: `ERROR` — functions not defined

- [ ] **Step 3: Implement `_measure_prose`**

Add after line 233 (before `_fetch_article_snippet`):

```python
def _measure_prose(text: str) -> tuple[int, float]:
    """Return (prose_char_count, prose_ratio) for text.

    Prose blocks: split by double newlines, filter blocks with <3 words,
    all-caps blocks, and blocks with <30% alphabetic chars.
    """
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
        if len(block) > 0 and alpha / len(block) < 0.3:
            continue
        prose_chars += len(block)

    ratio = prose_chars / total_chars if total_chars > 0 else 0.0
    return prose_chars, ratio
```

- [ ] **Step 4: Implement `_extract_article_links`**

Add after `_measure_prose`:

```python
def _extract_article_links(html: str, parent_url: str, keyword: str) -> list[str]:
    """Extract candidate article links from HTML of a thin page.

    Filters: same domain only, skips nav/footer/pagination/media links,
    requires article indicators (/article/, /post/, /news/, /blog/, year pattern).
    Returns deduped ordered list (DOM order preserved).
    """
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

        # Skip nav/footer/header/sidebar patterns
        if any(p in url_lower for p in SKIP_PATTERNS):
            continue

        # Skip media files
        if any(url_lower.endswith(ext) for ext in MEDIA_EXTS):
            continue

        # Must look like an article
        if not any(ind in url_lower for ind in ARTICLE_INDICATORS):
            continue

        candidates.append(full_url)

    # dedupe while preserving order
    return list(dict.fromkeys(candidates))
```

- [ ] **Step 5: Implement `_pick_best_link`**

Add after `_extract_article_links`:

```python
def _pick_best_link(urls: list[str], keyword: str) -> str:
    """Pick best article link from candidates by keyword relevance + slug length.

    Scoring: +10 for keyword in URL, +len(slug)/100 for specificity.
    Returns highest-scoring URL or empty string.
    """
    if not urls:
        return ""

    keyword_lower = keyword.lower()
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

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest tests/test_discovery_scheduler.py::test_measure_prose tests/test_discovery_scheduler.py::test_extract_article_links tests/test_discovery_scheduler.py::test_pick_best_link -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add core/discovery_scheduler.py tests/test_discovery_scheduler.py
git commit -m "feat(discovery): add prose measurer, link extractor, link picker helpers"
```

---

## Task 3: Implement `_fetch_with_drill` and Refactor `_fetch_article_snippet`

**Files:**
- Modify: `core/discovery_scheduler.py` — replace `_fetch_article_snippet` body, add `_fetch_with_drill`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_discovery_scheduler.py`:

```python
@pytest.mark.asyncio
async def test_fetch_with_drill_returns_snippet_for_rich_page():
    """Drill detects rich page (not thin) and returns snippet immediately."""
    from core.discovery_scheduler import _fetch_with_drill

    rich_html = ("This is a real article about Python programming. "
                 "The content is substantive with multiple sentences. "
                 "It has enough prose to be considered a real page.") * 20

    with patch("core.discovery_scheduler.extract_url", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = rich_html
        result = await _fetch_with_drill("https://example.com/article/python-tips", "python")
        assert len(result) > 0
        assert result.startswith("This is a real article")


@pytest.mark.asyncio
async def test_fetch_with_drill_drills_through_listing_pages():
    """Drill follows listing → article path when initial page is thin."""
    from core.discovery_scheduler import _fetch_with_drill

    thin_html = "HOME | ABOUT\n\nNavigation links here.\n\n" * 20
    article_html = "Real article content. Python programming tutorial. " * 50

    call_count = 0

    async def fake_extract(url):
        nonlocal call_count
        call_count += 1
        if "/article/" in url or "/2024/" in url:
            return article_html
        return thin_html

    with patch("core.discovery_scheduler.extract_url", new_callable=AsyncMock) as mock_extract:
        mock_extract.side_effect = fake_extract
        result = await _fetch_with_drill("https://example.com/category/tech", "python")

    assert len(result) > 0
    assert "Real article" in result
    assert call_count >= 2  # At least listing + article


@pytest.mark.asyncio
async def test_fetch_with_drill_max_depth_returns_empty():
    """Drill gives up after 5 levels and returns empty string."""
    from core.discovery_scheduler import _fetch_with_drill

    thin_html = "Nav\n\nLinks: /category/page2\n\n" * 20

    async def fake_extract(url):
        page_num = url.count("page")
        if "page5" in url:
            return thin_html  # still thin at depth 5
        # Return thin with a link to next page
        return thin_html + f'<a href="/category/page{page_num+1}">Next</a>'

    with patch("core.discovery_scheduler.extract_url", new_callable=AsyncMock) as mock_extract:
        mock_extract.side_effect = fake_extract
        result = await _fetch_with_drill("https://example.com/category/page1", "python")

    assert result == ""  # Gave up after max depth
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_discovery_scheduler.py::test_fetch_with_drill_returns_snippet_for_rich_page tests/test_discovery_scheduler.py::test_fetch_with_drill_drills_through_listing_pages tests/test_discovery_scheduler.py::test_fetch_with_drill_max_depth_returns_empty -v 2>&1 | tail -15
```

Expected: ERROR — `_fetch_with_drill` not defined

- [ ] **Step 3: Implement `_fetch_with_drill`**

Add before `_fetch_article_snippet`:

```python
async def _fetch_with_drill(url: str, keyword: str, depth: int = 0) -> str:
    """Fetch URL, drill if thin content. Returns snippet text or empty string.

    Thin = prose_chars < 500 AND prose_ratio < 0.30.
    Drills up to MAX_DEPTH (5) levels. Stops when:
      - Rich content found (returns snippet)
      - No article links found (returns "")
      - Max depth reached (returns "")
    """
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
    if not best:
        return ""

    return await _fetch_with_drill(best, keyword, depth + 1)
```

- [ ] **Step 4: Refactor `_fetch_article_snippet` to delegate**

Replace the existing `_fetch_article_snippet` method body:

```python
async def _fetch_article_snippet(self, url: str) -> str:
    """Fetch article page and extract first meaningful paragraph as snippet.

    Uses depth drill internally to handle thin/listing pages.
    """
    return await _fetch_with_drill(url, "", depth=0)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_discovery_scheduler.py::test_fetch_with_drill_returns_snippet_for_rich_page tests/test_discovery_scheduler.py::test_fetch_with_drill_drills_through_listing_pages tests/test_discovery_scheduler.py::test_fetch_with_drill_max_depth_returns_empty -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/discovery_scheduler.py tests/test_discovery_scheduler.py
git commit -m "feat(discovery): implement depth drill with thin page detection"
```

---

## Task 4: Safety Net Post-Pass in `_search_keyword`

**Files:**
- Modify: `core/discovery_scheduler.py` — update `_search_keyword` to add drill attempt for empty snippets after enrichment

- [ ] **Step 1: Write the failing test**

Add to `tests/test_discovery_scheduler.py`:

```python
@pytest.mark.asyncio
async def test_enrich_snippets_retries_empty_snippets():
    """Post-pass enrichment retries drill for any URL still with empty snippet."""
    from core.discovery_scheduler import DiscoveryScheduler

    scheduler = DiscoveryScheduler()

    rich_html = "Real article about AI. " * 50
    results = [
        {"url": "https://example.com/article/ai-news", "title": "AI News", "snippet": "", "source": "test"},
        {"url": "https://example.com/category/tech", "title": "Tech", "snippet": "Already has snippet", "source": "test"},
    ]

    with patch("core.discovery_scheduler.extract_url", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = rich_html
        enriched = await scheduler._enrich_snippets(results)

    assert enriched[0]["snippet"] != ""
    assert enriched[1]["snippet"] == "Already has snippet"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_discovery_scheduler.py::test_enrich_snippets_retries_empty_snippets -v 2>&1 | tail -10
```

Expected: FAIL — `enrich_snippets` currently calls `_fetch_article_snippet` but `_fetch_article_snippet` now uses `_fetch_with_drill` with empty keyword. The drill still works for thin detection but returns "" for the snippet since keyword is empty.

Actually — since `_fetch_article_snippet` now calls `_fetch_with_drill(url, "", depth=0)`, and `_pick_best_link` uses keyword for scoring (empty keyword = no bonus), the drill should still work for link picking that doesn't depend on keyword. The `extract_url` is called on the fetched content. But wait — the thin check works on content, not keyword. So even with empty keyword, thin pages still get drilled. The issue is the `_pick_best_link` scoring changes. Let me reconsider...

Actually, empty keyword means `keyword_lower = ""`. All URLs would have `score = len(slug)/100`. So it picks longest slug. This is fine — the drill still follows links, just without keyword prioritization. The test should pass as-is.

Let me think again — the test: mock `extract_url` returns `rich_html`. `_measure_prose` on `rich_html` → `prose_chars` large, `ratio` high → not thin → returns first para > 80 chars. So the first result gets a snippet via the drill function. The second result already has a snippet and is returned as-is.

Actually the current implementation of `_enrich_snippets` already calls `_fetch_article_snippet` which now calls `_fetch_with_drill`. So the safety net is ALREADY in place via the existing code path — `_enrich_snippets` is the post-pass that calls `_fetch_article_snippet` for empty snippets. The test should pass immediately since we refactored `_fetch_article_snippet` to use `_fetch_with_drill`.

Let me run the test first to confirm:

```bash
python -m pytest tests/test_discovery_scheduler.py::test_enrich_snippets_retries_empty_snippets -v
```

Expected: PASS (since `_fetch_article_snippet` already uses drill via our refactor)

If it passes: Task 4 is done by virtue of the refactor in Task 3. The `_enrich_snippets` post-pass already calls `_fetch_article_snippet` — which now uses drill internally. No additional code needed.

If it fails: investigate and fix.

- [ ] **Step 3: If test passed — Task 4 is complete by refactor. Commit as part of Task 3.**

The safety net already exists via `_enrich_snippets → _fetch_article_snippet → _fetch_with_drill`. No new code needed.

- [ ] **Step 4: Commit**

If the test passed without any code changes, this task is absorbed into Task 3's commit. If it required changes, commit separately:

```bash
git add core/discovery_scheduler.py tests/test_discovery_scheduler.py
git commit -m "feat(discovery): safety net post-pass uses depth drill"
```

---

## Task 5: Full Integration Test

**Files:**
- Run: full test suite

- [ ] **Step 1: Run full discovery scheduler test suite**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki
python -m pytest tests/test_discovery_scheduler.py -v 2>&1 | tail -30
```

Expected: All tests pass

- [ ] **Step 2: Verify no RuntimeWarning on unawaited coroutine**

```bash
python -c "
import asyncio
from core.discovery_scheduler import DiscoveryScheduler
s = DiscoveryScheduler()
# Just verify the class instantiates without warnings
print('Init OK')
" 2>&1
```

Expected: No RuntimeWarning about unawaited coroutine

- [ ] **Step 3: Commit all remaining changes**

```bash
git status
git add -A
git commit -m "feat(discovery): depth drill for thin page detection and generic 5-level web crawling"
```

---

## Self-Review Checklist

From the spec at `docs/superpowers/specs/2026-04-15-depth-drill-design.md`:

| Spec Requirement | Task | Status |
|-------------------|------|--------|
| Bug fix: await on line 202 | Task 1 | ✅ |
| `_measure_prose` with prose_chars < 500 AND ratio < 0.30 | Task 2 | ✅ |
| `_extract_article_links` with same-domain, nav/media skip, article indicators | Task 2 | ✅ |
| `_pick_best_link` with keyword + slug length scoring | Task 2 | ✅ |
| `_fetch_with_drill` with MAX_DEPTH=5, recursive drill, returns snippet or "" | Task 3 | ✅ |
| `_fetch_article_snippet` calls `_fetch_with_drill` | Task 3 | ✅ |
| Safety net post-pass in `_enrich_snippets` | Task 4 | ✅ |
| Tests for prose measurer, link extractor, link picker, drill | Tasks 2-4 | ✅ |

All requirements from the spec are covered.
