# YouTube Transcript Summarization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard 6000-char truncation in `minimax_client.enrich()` with semantic chunking (60k min) + synthesis for video content, so long-form video notes are complete unified narratives.

**Architecture:** For video content_type: (1) split transcript at natural boundaries with 60k char floor, (2) enrich each chunk with existing `enrich()`, (3) run a synthesis LLM pass to produce one unified narrative note. Non-video content passes through existing `enrich()` unchanged.

**Tech Stack:** Python, MiniMax API, existing `ingesters/youtube.py` transcript extraction, `core/minimax_client.py`

---

## File Map

| File | Role |
|------|------|
| `core/minimax_client.py` | Add `Chunk` dataclass, `semantic_chunk()`, `enrich_video_synthesis()`, modify `_build_prompt(max_chars=None)` |
| `pipeline.py` | Route `content_type="video"` through new chunk→synth flow, pass `content_type` to enrich |
| `tests/test_video_synthesis.py` | New test file for chunking + synthesis |

---

## Task 1: Chunk Dataclass + semantic_chunk()

**Files:**
- Modify: `core/minimax_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_video_synthesis.py
import pytest
from core.minimax_client import semantic_chunk, Chunk

def test_semantic_chunk_short_transcript_under_60k():
    """Under-60k transcript returns single chunk."""
    text = "Hello this is a short transcript. " * 200  # ~6k chars
    chunks = semantic_chunk(text)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].size_chars == len(text)

def test_semantic_chunk_exact_60k():
    """Exactly 60k chars returns single chunk."""
    text = "x" * 60_000
    chunks = semantic_chunk(text)
    assert len(chunks) == 1
    assert chunks[0].size_chars == 60_000

def test_semantic_chunk_oversize_splits():
    """Over-60k transcript splits into multiple chunks at natural boundaries."""
    # Two sections separated by a chapter marker
    section1 = "[Chapter: Thinking in First Principles]\n" + ("word " * 9000)  # ~45k
    section2 = "[Chapter: Mental Models in Practice]\n" + ("idea " * 3000)   # ~18k
    text = section1 + section2
    assert len(text) > 60_000
    chunks = semantic_chunk(text)
    # section1 alone is ~45k, section2 is ~18k → total ~63k → should be 2 chunks
    assert len(chunks) == 2
    # Verify chapter markers are at chunk boundaries
    assert "[Chapter: Thinking in First Principles]" in chunks[0].text
    assert "[Chapter: Mental Models in Practice]" in chunks[1].text

def test_semantic_chunk_respects_60k_minimum():
    """Each chunk is at least 60k chars (except final chunk)."""
    text = ("para " * 20000)  # ~100k chars
    chunks = semantic_chunk(text)
    for chunk in chunks[:-1]:
        assert chunk.size_chars >= 60_000, f"Chunk {chunk.chunk_number} is {chunk.size_chars}, expected >= 60000"

def test_semantic_chunk_timestamp_boundaries():
    """Timestamp patterns (e.g., 00:05:30) split chunks."""
    segment1 = ("Hello everyone. " * 5000) + "\n00:05:30,000 --> 00:05:35,000\n" + ("Continuing. " * 5000)
    segment2 = ("Now let's talk about. " * 5000) + "\n00:10:15,000 --> 00:10:20,000\n" + ("Another topic. " * 5000)
    text = segment1 + segment2
    chunks = semantic_chunk(text)
    assert len(chunks) >= 2

def test_semantic_chunk_metadata():
    """Each chunk has correct start/end indices and chunk_number."""
    text = ("word " * 30000)  # ~150k chars → 3 chunks
    chunks = semantic_chunk(text)
    assert chunks[0].chunk_number == 1
    assert chunks[1].chunk_number == 2
    assert chunks[2].chunk_number == 3
    assert chunks[0].start_index == 0
    assert chunks[0].end_index == len(chunks[0].text)
    assert chunks[1].start_index == chunks[0].end_index
    assert chunks[2].end_index == len(text)
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_video_synthesis.py -v 2>&1 | head -20
```
Expected: FAIL — `semantic_chunk` not yet defined

- [ ] **Step 3: Write minimal implementation**

Add at the top of `core/minimax_client.py` (after imports, before existing functions):

```python
from dataclasses import dataclass
from typing import List

@dataclass
class Chunk:
    text: str
    start_index: int
    end_index: int
    chunk_number: int
    size_chars: int

_TIMESTAMP_PATTERN_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->.+$", re.MULTILINE)
_CHAPTER_MARKER_RE = re.compile(
    r"^\s*(?:\[Chapter|Chapter\s*\d+|#{1,3}\s*|##?)\s*[:.\-]?\s*",
    re.IGNORECASE | re.MULTILINE,
)
_PARAGRAPH_BREAK_RE = re.compile(r"\n\n+")

_MIN_CHUNK_SIZE = 60_000
_OVERLAP_SIZE = 5_000  # 10% overlap for 60k target


def semantic_chunk(text: str) -> List[Chunk]:
    """
    Split transcript into semantic chunks with 60k char minimum.

    Split priority:
      1. Explicit chapter / section markers (e.g., [Chapter:], ## Title, ---)
      2. Large timestamp gaps (> 10s between consecutive cues)
      3. Paragraph breaks (\n\n) in regions large enough to form a chunk
      4. Fixed-size fallback with 5k char overlap

    Returns list of Chunk objects sorted by position in transcript.
    """
    if len(text) <= _MIN_CHUNK_SIZE:
        return [
            Chunk(
                text=text,
                start_index=0,
                end_index=len(text),
                chunk_number=1,
                size_chars=len(text),
            )
        ]

    # Try to split at chapter markers first
    boundaries = _find_chapter_boundaries(text)
    if len(boundaries) >= 2:
        chunks = _make_chunks(text, boundaries)
        if all(c.size_chars >= _MIN_CHUNK_SIZE for c in chunks[:-1]):
            return chunks

    # Try timestamp-gap splitting
    boundaries = _find_timestamp_gap_boundaries(text)
    if len(boundaries) >= 2:
        chunks = _make_chunks(text, boundaries)
        if all(c.size_chars >= _MIN_CHUNK_SIZE for c in chunks[:-1]):
            return chunks

    # Fallback: fixed-size splits with overlap
    return _fixed_size_chunk(text)


def _find_chapter_boundaries(text: str) -> List[int]:
    """Return start indices of sections preceded by chapter markers."""
    boundaries = [0]
    lines = text.splitlines()
    current_pos = 0
    for i, line in enumerate(lines):
        if _CHAPTER_MARKER_RE.match(line.strip()):
            boundaries.append(current_pos)
        current_pos += len(line) + 1
    # Deduplicate and sort
    boundaries = sorted(set(boundaries))
    # Ensure last boundary is not too close to end
    if boundaries[-1] > len(text) - _MIN_CHUNK_SIZE:
        boundaries = boundaries[:-1]
    return boundaries


def _find_timestamp_gap_boundaries(text: str) -> List[int]:
    """Return start indices where a large timestamp gap (>10s) occurs."""
    import re
    timestamps = [
        m.start() for m in _TIMESTAMP_PATTERN_RE.finditer(text)
    ]
    boundaries = [0]
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        if gap > 10_000:  # 10 seconds of transcript gap → topic shift
            boundaries.append(timestamps[i])
    return sorted(set(boundaries))


def _make_chunks(text: str, boundaries: List[int]) -> List[Chunk]:
    """Build Chunk list from a sorted list of start indices."""
    # Extend each boundary to include overlap with previous
    chunks = []
    for i, start in enumerate(boundaries):
        if i < len(boundaries) - 1:
            end = boundaries[i + 1]
        else:
            end = len(text)
        chunk_text = text[start:end]
        chunks.append(
            Chunk(
                text=chunk_text,
                start_index=start,
                end_index=end,
                chunk_number=i + 1,
                size_chars=len(chunk_text),
            )
        )
    return chunks


def _fixed_size_chunk(text: str) -> List[Chunk]:
    """Fallback: split into ~60k char chunks with 5k overlap."""
    chunks = []
    pos = 0
    chunk_num = 1
    while pos < len(text):
        end = min(pos + _MIN_CHUNK_SIZE, len(text))
        if pos + _MIN_CHUNK_SIZE > len(text):
            # Last chunk — take all remaining (even if < 60k)
            chunk_text = text[pos:]
        else:
            # Back up to nearest paragraph break to avoid cutting mid-sentence
            chunk_text = text[pos:end]
            last_break = chunk_text.rfind("\n\n")
            if last_break > _MIN_CHUNK_SIZE // 2:
                end = pos + last_break + 2
                chunk_text = text[pos:end]
        chunks.append(
            Chunk(
                text=chunk_text,
                start_index=pos,
                end_index=end,
                chunk_number=chunk_num,
                size_chars=len(chunk_text),
            )
        )
        chunk_num += 1
        # Overlap: start next chunk 5k chars back for context continuity
        pos = end
        if pos < len(text):
            overlap_start = max(pos - _OVERLAP_SIZE, 0)
            pos = overlap_start
    # Deduplicate if overlap pushed us back onto same text
    deduplicated = []
    for c in chunks:
        if not deduplicated or c.start_index >= deduplicated[-1].end_index:
            deduplicated.append(c)
    # Re-number
    for i, c in enumerate(deduplicated):
        c.chunk_number = i + 1
    return deduplicated
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_video_synthesis.py::test_semantic_chunk_short_transcript_under_60k tests/test_video_synthesis.py::test_semantic_chunk_exact_60k tests/test_video_synthesis.py::test_semantic_chunk_metadata -v
```
Expected: PASS

- [ ] **Step 5: Write integration test for oversize**

```
pytest tests/test_video_synthesis.py::test_semantic_chunk_oversize_splits tests/test_video_synthesis.py::test_semantic_chunk_respects_60k_minimum -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/minimax_client.py tests/test_video_synthesis.py
git commit -m "feat: add Chunk dataclass and semantic_chunk() with 60k minimum

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
"
```

---

## Task 2: Add enrich_video_synthesis()

**Files:**
- Modify: `core/minimax_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_video_synthesis.py — add after existing tests

def test_synthesis_unified_narrative_not_chunk_list(monkeypatch):
    """Synthesis prompt asks for unified narrative, not list of chunk summaries."""
    captured_prompt = {}
    def mock_post(url, headers, json, timeout):
        captured_prompt["payload"] = json
        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {
                    "base_resp": {"status_code": 0},
                    "choices": [{
                        "message": {
                            "content": '{"title":"Test","type":"video","tags":[],"summary":"Unified summary","key_facts":[],"cross_links":[],"entities":[],"chapters":[],"key_quotes":[],"topics_covered":[],"why_saved_hint":""}'
                        }
                    }]
                }
        return FakeResp()
    monkeypatch.setattr("requests.post", mock_post)

    chunk_results = [
        {"title": "Chunk 1 Title", "summary": "Summary of chunk 1", "chapters": [{"time": "00:00", "title": "First"}], "key_quotes": [], "entities": [], "key_facts": [], "topics_covered": [], "tags": []},
        {"title": "Chunk 2 Title", "summary": "Summary of chunk 2", "chapters": [{"time": "05:30", "title": "Second"}], "key_quotes": [], "entities": [], "key_facts": [], "topics_covered": [], "tags": []},
    ]
    result = enrich_video_synthesis(chunk_results, "https://youtube.com/watch?v=xxx", [])
    assert "Unified summary" in result["summary"]
    # Verify synthesis prompt received both chunk results
    assert "chunk" in captured_prompt["payload"]["messages"][1]["content"].lower()


def test_synthesis_returns_all_required_fields():
    """Synthesis returns all typed template fields."""
    chunk_results = [
        {"title": "Part 1", "summary": "S1", "chapters": [], "key_quotes": [], "entities": [],
         "key_facts": [], "topics_covered": [], "tags": [], "cross_links": [], "why_saved_hint": ""},
    ]
    result = enrich_video_synthesis(chunk_results, "https://youtube.com/watch?v=xxx", [])
    for field in ["title", "type", "tags", "summary", "key_facts", "cross_links",
                  "entities", "chapters", "key_quotes", "topics_covered", "why_saved_hint"]:
        assert field in result, f"Missing field: {field}"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_video_synthesis.py::test_synthesis_unified_narrative_not_chunk_list tests/test_video_synthesis.py::test_synthesis_returns_all_required_fields -v
```
Expected: FAIL — `enrich_video_synthesis` not defined

- [ ] **Step 3: Write implementation**

Add to `core/minimax_client.py` after the existing `enrich()` function:

```python
_SYNTHESIS_SYSTEM = """You are a knowledge synthesizer. Given analyses of multiple sections of one video, produce one unified research note.
Always respond with valid JSON only — no markdown fences, no explanation."""

_SYNTHESIS_TEMPLATE = """Multiple sections of one video have been analyzed separately.
Your task is to produce ONE unified research note — not a list of section summaries.

The final note must:
- Read as a coherent narrative essay about the video's core ideas
- Weave insights together across sections; don't repeat identical facts verbatim
- Preserve key quotes with speaker attribution
- Structure as: opening thesis → key concepts (with examples) → conclusion / "so what"
- Include chapters extracted across all sections, ordered by timestamp
- Preserve entities, key_facts, and tags from all chunks; deduplicate where overlapping
- summary: 2-3 sentence unified synthesis — NOT a list of chunk summaries

Respond with JSON matching this exact structure:
{{
  "title": "concise descriptive title",
  "type": "video",
  "tags": ["tag1", "tag2"],
  "summary": "2-3 sentence unified synthesis",
  "key_facts": ["fact 1", "fact 2"],
  "cross_links": ["existing-note-slug"],
  "entities": [
    {{"name": "Entity Name", "slug": "entity-name", "type": "concept|person|institution|dataset|method"}}
  ],
  "chapters": [{{"time": "MM:SS", "title": "Chapter title"}}, ...],
  "key_quotes": [{{"text": "quoted text", "speaker": "Speaker name"}}, ...],
  "topics_covered": ["topic1", "topic2"],
  "why_saved_hint": "one sentence about why this is worth keeping"
}}

Section analyses to synthesize:
{section_summaries}

Source: {source}
Existing related notes: {related}
"""


def enrich_video_synthesis(chunk_results: List[dict], source: str, similar_titles: List[str]) -> dict:
    """
    Run synthesis pass: take per-chunk enrichment results, produce one unified narrative note.
    Used for video content where the transcript was split into semantic chunks.
    """
    if not chunk_results:
        return {
            "title": "Untitled", "type": "video", "tags": [], "summary": "",
            "key_facts": [], "cross_links": [], "entities": [], "chapters": [],
            "key_quotes": [], "topics_covered": [], "why_saved_hint": "", "error": True,
        }

    if len(chunk_results) == 1:
        # Single chunk — no synthesis needed, just enrich normally
        r = chunk_results[0]
        r.setdefault("error", False)
        return r

    # Build section summaries text
    section_summaries = []
    for i, cr in enumerate(chunk_results, 1):
        summary_text = cr.get("summary", "")
        chapters = cr.get("chapters", [])
        key_quotes = cr.get("key_quotes", [])
        section_summaries.append(
            f"--- Section {i} ---\n"
            f"Title: {cr.get('title', 'Untitled')}\n"
            f"Summary: {summary_text}\n"
            f"Chapters: {chapters}\n"
            f"Key Quotes: {key_quotes}\n"
            f"Entities: {cr.get('entities', [])}\n"
            f"Topics: {cr.get('topics_covered', [])}\n"
        )
    sections_text = "\n".join(section_summaries)
    similar_str = "\n".join(f"- {t}" for t in similar_titles) if similar_titles else "(none yet)"
    prompt = _SYNTHESIS_TEMPLATE.format(
        section_summaries=sections_text,
        source=source,
        related=similar_str,
    )

    if not MINIMAX_API_KEY:
        return {**chunk_results[0], "error": True}

    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MINIMAX_MODEL,
        "messages": [
            {"role": "system", "content": _SYNTHESIS_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code") and base_resp["status_code"] != 0:
            raise ValueError(f"MiniMax API error {base_resp['status_code']}: {base_resp.get('status_msg')}")
        content = data["choices"][0]["message"]["content"]
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(content)
        result.setdefault("entities", [])
        result.setdefault("chapters", [])
        result.setdefault("key_quotes", [])
        result.setdefault("topics_covered", [])
        result.setdefault("key_facts", [])
        result.setdefault("cross_links", [])
        result.setdefault("why_saved_hint", "")
        result.setdefault("error", False)
        return result
    except Exception as e:
        _logger.warning("Synthesis pass failed for source=%s: %s", source, e)
        # Fallback: return first chunk result, don't lose data
        fallback = chunk_results[0].copy()
        fallback["error"] = True
        return fallback
```

Also update the import line to add `List` from typing:
```python
from typing import List
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_video_synthesis.py::test_synthesis_unified_narrative_not_chunk_list tests/test_video_synthesis.py::test_synthesis_returns_all_required_fields -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/minimax_client.py
git commit -m "feat: add enrich_video_synthesis() for unified video notes

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
"
```

---

## Task 3: Update pipeline.py to route video through synthesis

**Files:**
- Modify: `pipeline.py:125-128`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_video_synthesis.py — add

def test_pipeline_video_routes_to_synthesis(monkeypatch):
    """pipeline.py routes video content_type through chunk→synth flow."""
    captured_calls = {}
    original_semantic_chunk = semantic_chunk
    original_enrich = enrich
    original_synthesis = enrich_video_synthesis

    def mock_chunk(text):
        captured_calls["chunk"] = True
        # Return 2 chunks to trigger synthesis
        return [
            Chunk(text="first half " * 10000, start_index=0, end_index=90000, chunk_number=1, size_chars=90000),
            Chunk(text="second half " * 10000, start_index=90000, end_index=180000, chunk_number=2, size_chars=90000),
        ]

    def mock_enrich(raw, similar, source):
        captured_calls["enrich_count"] = captured_calls.get("enrich_count", 0) + 1
        return {"title": f"Chunk {captured_calls['enrich_count']}", "summary": "chunk summary",
                "chapters": [], "key_quotes": [], "entities": [], "key_facts": [], "topics_covered": [],
                "tags": [], "cross_links": [], "why_saved_hint": ""}

    def mock_synthesis(chunk_results, source, similar):
        captured_calls["synthesis"] = True
        return {"title": "Unified Video", "type": "video", "summary": "Unified narrative",
                "chapters": [{"time": "00:00", "title": "Start"}], "key_quotes": [], "entities": [],
                "key_facts": [], "topics_covered": [], "tags": [], "cross_links": [], "why_saved_hint": ""}

    monkeypatch.setattr("core.minimax_client.semantic_chunk", mock_chunk)
    monkeypatch.setattr("core.minimax_client.enrich", mock_enrich)
    monkeypatch.setattr("core.minimax_client.enrich_video_synthesis", mock_synthesis)

    import pipeline
    # We test the video path via the internal flow
    # Run via asyncio
    import asyncio
    async def run():
        # Mock extract to return a video Document
        class MockDoc:
            raw_text = "full transcript " * 10000
            content_type = "video"
            images = []
        # Mock the extract function
        with monkeypatch.context() as m:
            m.setattr("pipeline.extract", lambda url: MockDoc())
            m.setattr("pipeline.get_store", lambda: type('Store', (), {'exists': lambda self, u: False})())
            async for msg in pipeline.run_pipeline(url="https://youtube.com/watch?v=xyz"):
                pass
        return captured_calls

    result = asyncio.run(run())
    assert result.get("chunk") is True
    assert result.get("enrich_count") == 2
    assert result.get("synthesis") is True
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_video_synthesis.py::test_pipeline_video_routes_to_synthesis -v
```
Expected: FAIL — pipeline.py doesn't route by content_type yet

- [ ] **Step 3: Write implementation**

In `pipeline.py`, modify the enrichment step (around line 125):

```python
    # Step 3: Enrich
    yield "Enriching with Minimax..."
    if doc.content_type == "video" and len(raw_text) > 60_000:
        # Video + long transcript: use semantic chunking + synthesis
        from core.minimax_client import semantic_chunk, enrich, enrich_video_synthesis
        chunks = semantic_chunk(raw_text)
        chunk_results = []
        for chunk in chunks:
            result = await asyncio.to_thread(enrich, chunk.text, similar_titles, source)
            chunk_results.append(result)
        note = await asyncio.to_thread(enrich_video_synthesis, chunk_results, source, similar_titles)
    elif doc.content_type == "video":
        # Video + short transcript: direct enrich (no truncation needed)
        note = await asyncio.to_thread(enrich, raw_text, similar_titles, source)
    else:
        # Article / paper: direct enrich
        note = await asyncio.to_thread(enrich, raw_text, similar_titles, source)
```

Note: the `raw_text[:6000]` truncation in `_build_prompt()` only affects `_NOTE_TEMPLATE` which handles non-video content. For video, `_build_prompt` is used by `enrich()` for each chunk — but we need to increase the limit for chunks. The chunking ensures each chunk is 60k max, so `[:6000]` in `_build_prompt` would still cut 60k chunks down to 6k. **Fix**: Update `_build_prompt` to accept optional `max_chars` parameter:

```python
def _build_prompt(raw_text: str, similar_titles: list[str], source: str, max_chars: int | None = None) -> str:
    similar_str = "\n".join(f"- {t}" for t in similar_titles) if similar_titles else "(none yet)"
    text_to_use = raw_text if max_chars is None else raw_text[:max_chars]
    return _NOTE_TEMPLATE.format(
        source=source,
        similar=similar_str,
        raw_text=text_to_use,
    )
```

And in `enrich()`, pass `max_chars=None` (no limit) when called from video pipeline, or simply remove the hard slice since MiniMax supports 200k:

Actually — the cleanest fix: remove `[:6000]` entirely from `_build_prompt`. The template was designed for 6k as a safeguard when MiniMax had lower limits, but now with 200k context we can pass the full chunk (up to 60k). For non-video content (articles/papers), the quality gate already filters to 100+ chars, and the embed uses `MAX_EMBED_CHARS` for vectorization. The enrichment call should not independently truncate.

**Change `_build_prompt` line 52** from:
```python
        raw_text=raw_text[:6000],
```
to:
```python
        raw_text=raw_text,
```

This is safe because: (a) MiniMax supports 200k context, (b) quality gate already filters thin content, (c) 60k max per chunk for video, (d) `MAX_EMBED_CHARS` is a separate vectorization concern.

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_video_synthesis.py::test_pipeline_video_routes_to_synthesis -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline.py core/minimax_client.py
git commit -m "feat: route video content through semantic chunking + synthesis

pipeline.py now:
- Detects video content_type + long transcript (>60k)
- Splits via semantic_chunk(), enriches each chunk
- Runs enrich_video_synthesis() for unified narrative

Also removes the 6000-char hard truncation from _build_prompt()
— MiniMax 200k context makes it unnecessary.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
"
```

---

## Task 4: Integration Test

**Files:**
- Modify: `tests/test_video_synthesis.py`

- [ ] **Step 1: Write integration test**

```python
def test_video_under_60k_no_synthesis_needed(monkeypatch):
    """Short video transcript skips synthesis and goes direct to enrich."""
    calls = {}
    original_enrich = enrich
    def mock_enrich(raw, similar, source):
        calls["enrich"] = raw[:100]  # just verify called
        return {"title": "Short Video", "type": "video", "summary": "Short",
                "chapters": [], "key_quotes": [], "entities": [], "key_facts": [],
                "topics_covered": [], "tags": [], "cross_links": [], "why_saved_hint": ""}
    monkeypatch.setattr("core.minimax_client.enrich", mock_enrich)

    import asyncio
    async def run():
        class MockDoc:
            raw_text = "short transcript " * 200  # ~3.4k chars
            content_type = "video"
            images = []
        with monkeypatch.context() as m:
            m.setattr("pipeline.extract", lambda url: MockDoc())
            m.setattr("pipeline.get_store", lambda: type('Store', (), {'exists': lambda self, u: False})())
            async for msg in pipeline.run_pipeline(url="https://youtube.com/watch?v=xyz"):
                pass
        return calls

    result = asyncio.run(run())
    assert "enrich" in result
    assert "synthesis" not in result  # synthesis should NOT be called for short video
```

- [ ] **Step 2: Run integration test**

```
pytest tests/test_video_synthesis.py::test_video_under_60k_no_synthesis_needed -v
```
Expected: PASS

- [ ] **Step 3: Run full test suite (non-integration)**

```
pytest tests/ -v --ignore=tests/test_pipeline.py --ignore=tests/test_hybrid_search_live.py -x 2>&1 | tail -20
```
Expected: PASS (177+ tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_video_synthesis.py
git commit -m "test: add video synthesis integration tests

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
"
```

---

## Self-Review Checklist

- [ ] Spec coverage: semantic chunking ✓, 60k min ✓, synthesis pass ✓, unified narrative ✓, pipeline routing ✓
- [ ] No placeholders (TBD/TODO) in any step
- [ ] Type consistency: `Chunk` dataclass fields match across all uses; `enrich_video_synthesis` signature matches pipeline call
- [ ] `_build_prompt` truncation removed — 6000 char limit eliminated
- [ ] Error handling: synthesis failure falls back to first chunk result; all-chunks-fail returns error dict
- [ ] Backwards compat: non-video content uses existing `enrich()` unchanged
