# Pre-Write Content Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pre-write gate in `run_pipeline` that rejects enriched content with < 300 prose chars or < 20% prose ratio before `write_note()` is called.

**Architecture:** Extract `_measure_prose` from `discovery_scheduler.py` into a new `core/prose.py` module, then add `_gate_enriched_content()` to `pipeline.py` wired between enrichment (Step 3) and write (Step 4).

**Tech Stack:** Python 3.13, pytest, asyncio

---

## Task 1: Extract `core/prose.py`

**Files:**
- Create: `core/prose.py`
- Modify: `core/discovery_scheduler.py` (update import)

- [ ] **Step 1: Create `core/prose.py`** with extracted `_measure_prose`

```python
# core/prose.py
"""Prose quality measurement utilities."""
import re

def measure_prose(text: str) -> tuple[int, float]:
    """Return (prose_char_count, prose_ratio) for text.

    Prose blocks: split by double newlines, filter blocks with <3 words,
    all-caps blocks, and blocks with <30% alphabetic chars.
    """
    total_chars = len(text.strip())
    if total_chars == 0:
        return 0, 0.0

    blocks = re.split(r"\n\s*\n", text.strip())
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

- [ ] **Step 2: Update `core/discovery_scheduler.py` to use `core/prose.py`**

At the top of `discovery_scheduler.py`, add:
```python
from core.prose import measure_prose
```

Replace the local `_measure_prose` function (lines 46-74) with a one-liner that calls the module:
```python
def _measure_prose(text: str) -> tuple[int, float]:
    return measure_prose(text)
```

Keep `_measure_prose` as a wrapper so all existing internal callers (`_extract_article_links`, etc.) don't need to change.

- [ ] **Step 3: Run existing tests to verify no regression**

```bash
pytest tests/test_discovery_scheduler.py -v --timeout=30 2>&1 | head -50
```
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add core/prose.py core/discovery_scheduler.py
git commit -m "refactor: extract measure_prose to core/prose.py"
```

---

## Task 2: Add `_gate_enriched_content()` to `pipeline.py`

**Files:**
- Modify: `pipeline.py`

- [ ] **Step 1: Add import at top of `pipeline.py`**

```python
from core.prose import measure_prose
```

- [ ] **Step 2: Add `_gate_enriched_content()` function to `pipeline.py`** (after the `_run_gap_search_pipeline` function, around line 65):

```python
def _gate_enriched_content(note: dict, raw_text: str) -> tuple[bool, int, float]:
    """Return (pass, prose_chars, prose_ratio) for enriched content quality check.

    Checks:
    - Hard minimum: total prose chars >= 300
    - Prose ratio: prose_chars / raw_text_chars >= 0.20
    - Video-specific: raw_text must have >= 5 words with at least one alpha char
    """
    summary = note.get("summary", "") or ""
    key_facts_list = note.get("key_facts", [])
    key_facts = " ".join(key_facts_list) if key_facts_list else ""
    enriched_text = (summary + " " + key_facts).strip()

    prose_chars, prose_ratio = measure_prose(enriched_text)
    total_chars = len(raw_text.strip())

    # Hard minimum: need meaningful prose
    if prose_chars < 300:
        return False, prose_chars, prose_ratio

    # Prose ratio: content must not be mostly noise
    if total_chars > 0 and prose_ratio < 0.20:
        return False, prose_chars, prose_ratio

    # Video-specific: raw_text must have actual words (not just timestamps)
    if note.get("content_type") == "video":
        words = [w for w in raw_text.split() if any(c.isalpha() for c in w)]
        if len(words) < 5:
            return False, prose_chars, prose_ratio

    return True, prose_chars, prose_ratio
```

- [ ] **Step 3: Wire gate between Step 3 (enrich) and Step 4 (write) in `run_pipeline()`**

In `run_pipeline()`, after the enrich block (around line 143) and before the "Checking entity status" yield (around line 146):

```python
    # Step 3.1: Pre-write content quality gate — reject thin/noise-heavy enriched content
    gate_pass, prose_chars, prose_ratio = _gate_enriched_content(note, raw_text)
    if not gate_pass:
        yield f"Skipped: Content too thin (prose={prose_chars}, ratio={prose_ratio:.0%}, need ≥300 chars, ≥20%)"
        return
```

- [ ] **Step 4: Run existing pipeline tests to verify no regression**

```bash
pytest tests/test_pipeline.py -v --timeout=60 2>&1 | tail -20
```
Expected: all pass (existing tests should still work — the new gate is a hard reject on bad content, not a behavior change for good content)

- [ ] **Step 5: Commit**

```bash
git add pipeline.py
git commit -m "feat: add pre-write content quality gate rejecting thin/noise-heavy enriched notes"
```

---

## Task 3: Write tests for pre-write gate

**Files:**
- Create: `tests/test_pre_write_gate.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Create `tests/test_pre_write_gate.py`**

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _make_article_doc(raw_text: str, content_type: str = "article"):
    doc = MagicMock()
    doc.raw_text = raw_text
    doc.images = []
    doc.content_type = content_type
    return doc


def _make_enriched_note(summary: str, key_facts: list[str], content_type: str = "article"):
    return {
        "title": "Test Note",
        "type": content_type,
        "summary": summary,
        "key_facts": key_facts,
        "cross_links": [],
        "raw_text": "",
        "content_type": content_type,
        "error": False,
    }


@pytest.mark.asyncio
async def test_gate_rejects_thin_enriched_content():
    """Enriched summary + key_facts below 300 prose chars → skip."""
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    thin_enriched = _make_enriched_note(
        summary="Short.",
        key_facts=["Fact"],
    )

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("pipeline._is_pdf_url", return_value=False),
        patch("ingesters.news.extract_news", AsyncMock(return_value=_make_article_doc(
            "Real extracted content from the web page that is definitely over one hundred characters long for testing purposes. " * 5
        ))),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch("pipeline.enrich", return_value=thin_enriched),
    ):
        messages = []
        async for msg in run_pipeline(url="https://example.com/thin"):
            messages.append(msg)

    assert any("Skipped" in m for m in messages)
    assert any("Content too thin" in m for m in messages)
    # write_note should NOT have been called
    assert not any("Saved" in m for m in messages)


@pytest.mark.asyncio
async def test_gate_rejects_low_prose_ratio():
    """Content with high char count but < 20% prose ratio → skip."""
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    # Raw text is mostly timestamps + noise, only 20 prose chars in the summary
    noise_raw = "2024-01-15 14:30:00 2024-01-15 14:31:00 2024-01-15 14:32:00 [PAYWALLED] " + "x" * 500
    thin_summary = "Good prose here but short."

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("pipeline._is_pdf_url", return_value=False),
        patch("ingesters.news.extract_news", AsyncMock(return_value=_make_article_doc(noise_raw))),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch("pipeline.enrich", return_value=_make_enriched_note(
            summary=thin_summary,
            key_facts=[],
        )),
    ):
        messages = []
        async for msg in run_pipeline(url="https://example.com/noise"):
            messages.append(msg)

    assert any("Skipped" in m for m in messages)
    assert not any("Saved" in m for m in messages)


@pytest.mark.asyncio
async def test_gate_accepts_valid_enriched_content():
    """Substantial summary + key_facts with good prose ratio → write proceeds."""
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    good_raw = "Real extracted content from the web page that is definitely over one hundred characters long for testing purposes. " * 5
    good_summary = "This is a substantial summary with real meaningful content that explains what the article is about in detail."

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("pipeline._is_pdf_url", return_value=False),
        patch("ingesters.news.extract_news", AsyncMock(return_value=_make_article_doc(good_raw))),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch("pipeline.enrich", return_value=_make_enriched_note(
            summary=good_summary,
            key_facts=["Key fact one.", "Key fact two."],
        )),
        patch("pipeline.write_note", return_value="/vault/notes/good.md"),
        patch("pipeline.detect_gaps", return_value=[]),
    ):
        messages = []
        async for msg in run_pipeline(url="https://example.com/good"):
            messages.append(msg)

    assert any("Saved" in m for m in messages)
    assert not any("Skipped" in m for m in messages)


@pytest.mark.asyncio
async def test_gate_rejects_video_timestamp_heavy_transcript():
    """Video transcript with < 5 actual words (mostly timestamps) → skip."""
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    timestamp_transcript = """
    00:00 Introduction
    00:15 Welcome to this video
    00:30 Today we discuss
    00:45 Key points
    01:00 Conclusion
    """
    # This has enough chars but no coherent prose in the summary below 300

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("pipeline._is_pdf_url", return_value=False),
        patch("ingesters.news.extract_news", AsyncMock(return_value=_make_article_doc(
            timestamp_transcript,
            content_type="video"
        ))),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch("pipeline.enrich", return_value=_make_enriched_note(
            summary="Video about topics.",
            key_facts=["Point one.", "Point two."],
            content_type="video",
        )),
    ):
        messages = []
        async for msg in run_pipeline(url="https://youtube.com/watch?v=abc"):
            messages.append(msg)

    assert any("Skipped" in m for m in messages)
    assert not any("Saved" in m for m in messages)
```

- [ ] **Step 2: Run the new tests**

```bash
pytest tests/test_pre_write_gate.py -v --timeout=60 2>&1
```
Expected: 4 tests pass

- [ ] **Step 3: Run full pipeline test suite**

```bash
pytest tests/test_pipeline.py tests/test_pre_write_gate.py -v --timeout=60 2>&1 | tail -30
```
Expected: all pipeline tests + pre-write gate tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_pre_write_gate.py
git commit -m "test: add pre-write gate tests for thin/low-prose/video content"
```

---

## Task 4: Smoke test end-to-end in Docker

**Files:** None (verification only)

- [ ] **Step 1: Rebuild Docker container**

```bash
docker compose build personalwiki && docker compose up -d
```

- [ ] **Step 2: Verify crawl4ai works inside container**

```bash
docker compose exec personalwiki python3 -c "
import asyncio
from ingesters.web import extract_url
async def test():
    text = await extract_url('https://www.desprebursa.ro/publicatii/esti-cu-adevarat-pregatit')
    print(f'OK: {len(text)} chars')
asyncio.run(test())
" 2>&1 | grep OK
```
Expected: `OK: 14559 chars`

- [ ] **Step 3: Verify prose module works**

```bash
docker compose exec personalwiki python3 -c "
from core.prose import measure_prose
text = 'This is a substantial summary with real meaningful content. ' * 10
chars, ratio = measure_prose(text)
print(f'prose_chars={chars}, ratio={ratio:.0%}')
" 2>&1
```
Expected: `prose_chars=390, ratio=100%` (or similar high ratio)

---

## Spec Coverage Check

- [x] Pre-write gate added between Step 3 and Step 4 in `run_pipeline()` — Task 2
- [x] `measure_prose` extracted to `core/prose.py` — Task 1
- [x] Gate checks: hard minimum 300 prose chars, ratio 20%, video word check — Task 2
- [x] Skip message format matches spec — Task 2
- [x] Tests for thin enriched content, low prose ratio, valid content, video timestamps — Task 3
- [x] No changes to `QualityGate.check()` or `cleanup_junk()` — per spec, these stay
- [x] Discovery scheduler unchanged — gate fires inside `run_pipeline()` which it calls

---

## Files Summary

| File | Action |
|------|--------|
| `core/prose.py` | Create — extracted `measure_prose` |
| `core/discovery_scheduler.py` | Modify — import from `core/prose.py` |
| `pipeline.py` | Modify — add `_gate_enriched_content()` and wire it |
| `tests/test_pre_write_gate.py` | Create — 4 gate tests |
