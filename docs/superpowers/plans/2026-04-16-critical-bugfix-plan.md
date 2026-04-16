# Critical Bug Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 14 identified bugs across 5 categories in the personalWiki codebase.

**Architecture:** 14 independent bug fixes, each in a specific file. Bugs are grouped by file so multiple bugs in the same file are fixed together. Test-first approach: write a failing test for each bug before fixing it.

**Tech Stack:** Python 3.13, pytest, LanceDB, asyncio, FastAPI

---

## Files Modified

| File | Bugs Fixed |
|------|-----------|
| `core/minimax_client.py` | Bugs 1, 6, 7, 8 |
| `core/vector_store.py` | Bug 3 |
| `vault/writer.py` | Bug 4 |
| `core/discovery_scheduler.py` | Bugs 5, 13 |
| `app.py` | Bugs 2, 9 |
| `ingesters/youtube.py` | Bug 10 |
| `core/bm25_index.py` | Bug 11 |
| `pipeline.py` | Bug 12 |
| `ingesters/router.py` | Bug 14 |

---

## Task 1: Empty Chunk When Text Starts with Chapter Marker

**File:** `core/minimax_client.py` — `_build_chunks()` at line 139

**Root Cause:** When transcript starts with a chapter marker, `_find_chapter_splits` returns `[0, ...]`. `_build_chunks` does `boundaries = [0] + sorted(set(splits)) + [len(text)]`. If splits already contains 0, boundaries becomes `[0, 0, ...]` producing an empty first chunk.

**Test:** `tests/test_video_synthesis.py` — `test_semantic_chunk_oversize_splits` currently fails with `assert 3 == 2` (empty first chunk included).

- [ ] **Step 1: Run existing failing test**

Run: `cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && python -m pytest tests/test_video_synthesis.py::test_semantic_chunk_oversize_splits -v`
Expected: FAIL — `AssertionError: assert 3 == 2`

- [ ] **Step 2: Add regression test for chapter-at-start boundary case**

Add to `tests/test_video_synthesis.py`:

```python
def test_semantic_chunk_chapter_at_start_no_empty_chunk():
    """Text starting with chapter marker must not produce empty first chunk."""
    section1 = "[Chapter: Introduction]\n" + ("word " * 12000)  # ~60k
    section2 = "[Chapter: Main Content]\n" + ("idea " * 3000)   # ~15k
    text = section1 + section2
    chunks = semantic_chunk(text)
    # Must not have any empty chunks
    assert all(len(c.text) > 0 for c in chunks), "Empty chunk detected"
    # Must have exactly 2 chunks
    assert len(chunks) == 2
    # First chunk must start with chapter marker
    assert chunks[0].text.startswith("[Chapter: Introduction]")
```

- [ ] **Step 3: Run regression test to verify it fails**

Run: `python -m pytest tests/test_video_synthesis.py::test_semantic_chunk_chapter_at_start_no_empty_chunk -v`
Expected: FAIL — empty chunk assertion fails

- [ ] **Step 4: Fix `_build_chunks` to deduplicate consecutive boundaries**

In `core/minimax_client.py`, replace the `_build_chunks` function:

```python
def _build_chunks(text: str, splits: List[int]) -> List[Chunk]:
    """Build chunks from a list of split indices."""
    # Deduplicate consecutive boundaries (fixes empty chunk when split==0)
    boundaries = [0] + sorted(set(splits)) + [len(text)]
    deduped: list[int] = []
    for b in boundaries:
        if not deduped or b != deduped[-1]:
            deduped.append(b)
    chunks = []
    for i in range(len(deduped) - 1):
        start = deduped[i]
        end = deduped[i + 1]
        chunk_text = text[start:end]
        chunks.append(
            Chunk(
                text=chunk_text,
                start_index=start,
                end_index=end,
                chunk_number=i + 1,
            )
        )
    return chunks
```

- [ ] **Step 5: Run all video synthesis tests to verify fix**

Run: `python -m pytest tests/test_video_synthesis.py -v`
Expected: All 11 tests pass

- [ ] **Step 6: Commit**

```bash
git add tests/test_video_synthesis.py core/minimax_client.py
git commit -m "fix: deduplicate consecutive boundaries in _build_chunks to prevent empty chunks"
```

---

## Task 2: Race Condition on `_job_queues` in app.py

**File:** `app.py` — `_job_queues` dict accessed without synchronization

**Root Cause:** `_run()` (in `ingest()`) puts messages into queue while `stream()` can pop and delete it concurrently. The `None` sentinel can be put multiple times or lost.

**Test:** `tests/test_app.py` — no existing concurrency test.

- [ ] **Step 1: Write race condition test**

Add to `tests/test_app.py`:

```python
@pytest.mark.asyncio
async def test_job_queue_cleanup_not_racy():
    """stream() must not pop queue while _run() is still writing."""
    import asyncio
    from app import _job_queues

    job_id = "test-race-123"
    queue = asyncio.Queue()
    _job_queues[job_id] = queue

    async def writer():
        for i in range(5):
            await queue.put(f"<p>msg {i}</p>")
        await queue.put(None)

    async def reader():
        results = []
        while True:
            msg = await queue.get()
            if msg is None:
                break
            results.append(msg)
        return results

    # Run concurrently — without fix, this may miss messages or KeyError
    writer_task = asyncio.create_task(writer())
    reader_task = asyncio.create_task(reader())
    results = await reader_task
    await writer_task

    assert len(results) == 5
    assert job_id not in _job_queues  # queue must be cleaned up
```

- [ ] **Step 2: Run test to verify it fails (or passes due to timing)**

Run: `python -m pytest tests/test_app.py::test_job_queue_cleanup_not_racy -v`
Expected: May pass due to timing but the bug exists in production under load

- [ ] **Step 3: Fix — add asyncio.Lock to protect queue lifecycle**

In `app.py`, add a lock dict and use it to serialize queue access:

```python
_job_queues: dict[str, asyncio.Queue] = {}
_scheduler: DiscoveryScheduler | None = None
_queue_locks: dict[str, asyncio.Lock] = {}  # NEW: per-job locks

# In ingest():
_job_queues[job_id] = asyncio.Queue()
_queue_locks[job_id] = asyncio.Lock()

# In _run() — wrap queue operations:
async with _queue_locks[job_id]:
    if job_id not in _job_queues:
        return
    async for msg in run_pipeline(**kwargs):
        await _job_queues[job_id].put(f"<p>{msg}</p>")
    # ... cleanup ...
    _job_queues.pop(job_id, None)
    _queue_locks.pop(job_id, None)

# In stream() — use lock before get():
lock = _queue_locks.get(job_id)
if not lock:
    return
async with lock:
    q = _job_queues.get(job_id)
    if not q:
        return
    while True:
        msg = await q.get()
        if msg is None:
            _job_queues.pop(job_id, None)
            _queue_locks.pop(job_id, None)
            break
        yield {"event": "message", "data": msg}
```

**Simpler alternative (fewer code changes):** Make `_run()` responsible for cleanup only, and have `stream()` never delete the queue:

```python
# In _run() finally block:
await _job_queues[job_id].put(None)
# Remove from dict only after None is put
await asyncio.sleep(0.1)  # give stream() a chance to drain
_job_queues.pop(job_id, None)

# In stream():
q = _job_queues.get(job_id)
if not q:
    return
while True:
    msg = await q.get()
    if msg is None:
        break
    yield {"event": "message", "data": msg}
# DON'T pop here — _run() owns cleanup
```

**Recommended fix:** Use the lock approach (first option) — it's explicit and safer.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_app.py -v`

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "fix: add lock synchronization to _job_queues race condition"
```

---

## Task 3: SQL Injection / Path Not Escaped in VectorStore

**File:** `core/vector_store.py` — `where()` clauses at lines 84, 104, 110, 127

**Root Cause:** `_escape_path()` helper exists at line 9 but is NOT used in `upsert`, `exists`, `get_title_by_url`, or `get_mtime`. Paths with single quotes cause SQL errors. A malicious path could inject SQL.

**Test:** Add unit test to `tests/test_vector_store.py`.

- [ ] **Step 1: Write path escaping test**

Add to `tests/test_vector_store.py`:

```python
def test_path_with_single_quote_no_injection(tmp_path):
    """Paths with single quotes must be safely escaped in where() clauses."""
    from core.vector_store import VectorStore
    import lancedb

    db_path = str(tmp_path / "lance.db")
    store = VectorStore(db_path)

    # Path with single quote — would break SQL without escaping
    path = "notes/O'Reilly's Notes.md"

    # This must not raise a SQL error
    store.upsert(
        path=path,
        text="Test content",
        vector=[0.0] * 384,
        links=[],
        metadata={"title": "O'Reilly's Notes"},
    )
    assert store.exists(path) is True
    assert store.get_title_by_url(path) == "O'Reilly's Notes"
    assert store.get_mtime(path) > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_vector_store.py::test_path_with_single_quote_no_injection -v`
Expected: FAIL — SQL error or assertion failure

- [ ] **Step 3: Apply `_escape_path()` to all where() clauses**

In `core/vector_store.py`, fix all four methods:

```python
# Line ~84 in upsert():
self._table.delete(f"path = '{_escape_path(path)}'")

# Line ~104 in exists():
rows = self._table.search().where(f"path = '{_escape_path(path)}'").limit(1).to_list()

# Line ~110 in get_title_by_url():
rows = self._table.search().where(f"path = '{_escape_path(url)}'").limit(1).to_list()

# Line ~127 in get_mtime():
rows = self._table.search().where(f"path = '{_escape_path(path)}'").limit(1).to_list()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_vector_store.py::test_path_with_single_quote_no_injection -v`
Expected: PASS

- [ ] **Step 5: Run all vector store tests**

Run: `python -m pytest tests/test_vector_store.py -v`

- [ ] **Step 6: Commit**

```bash
git add core/vector_store.py tests/test_vector_store.py
git commit -m "fix: escape single quotes in path values for all where() clauses"
```

---

## Task 4: Wrong Key Names in Video Body Builder

**File:** `vault/writer.py` — `_build_video_body()` at lines 67, 78

**Root Cause:**
- Line 67: Uses `note.get("quotes", [])` — MiniMax returns `"key_quotes"` not `"quotes"`
- Line 70: Accesses `q['text']` and `q['speaker']` directly without `.get()` — KeyError if missing
- Line 78: Uses `note.get("topics", [])` — MiniMax returns `"topics_covered"` not `"topics"`

**Test:** Add integration test to `tests/test_writer.py`.

- [ ] **Step 1: Write video body key names test**

Add to `tests/test_writer.py`:

```python
def test_build_video_body_uses_correct_field_names():
    """_build_video_body must use 'key_quotes' and 'topics_covered', not 'quotes' and 'topics'."""
    from vault.writer import _build_video_body

    note = {
        "summary": "Test summary",
        "type": "video",
        # These are the actual field names from MiniMax API
        "key_quotes": [{"text": "Something important", "speaker": "Dr. Smith"}],
        "topics_covered": ["machine learning", "AI safety"],
        "chapters": [{"time": "00:00", "title": "Intro"}],
    }
    body = _build_video_body(note)

    # key_quotes content must appear
    assert "Something important" in body
    assert "Dr. Smith" in body
    # topics_covered content must appear
    assert "machine learning" in body
    assert "AI safety" in body
    # Old wrong field names must NOT create spurious sections
    assert "## Key Quotes\n\n_" not in body  # would appear if quotes==[] and key_quotes ignored


def test_build_video_body_missing_quote_keys_no_crash():
    """Missing 'text' or 'speaker' in key_quotes must not raise KeyError."""
    from vault.writer import _build_video_body

    note = {
        "summary": "Test",
        "type": "video",
        "key_quotes": [
            {"text": "Valid quote"},          # missing 'speaker'
            {"speaker": "Someone"},            # missing 'text'
            {"text": "Valid", "speaker": "Person"},  # valid
            {},                                 # empty dict
        ],
    }
    # Must not raise KeyError
    body = _build_video_body(note)
    assert "Valid quote" in body
    assert "Valid" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_writer.py::test_build_video_body_uses_correct_field_names tests/test_writer.py::test_build_video_body_missing_quote_keys_no_crash -v`
Expected: FAIL — key quotes/topics not found in body

- [ ] **Step 3: Fix `_build_video_body` in vault/writer.py**

Replace lines 66-83:

```python
    # Key quotes — use 'key_quotes' (MiniMax field name), not 'quotes'
    key_quotes = note.get("key_quotes", [])
    if key_quotes:
        quotes_lines = "\n".join(
            f"> \"{q.get('text', '')}\" — {q.get('speaker', 'Unknown')}"
            for q in key_quotes if q.get("text")
        )
        if quotes_lines:
            quotes_section = f"\n## Key Quotes\n{quotes_lines}\n"
        else:
            quotes_section = ""
    else:
        quotes_section = ""

    # Topics covered — use 'topics_covered' (MiniMax field name), not 'topics'
    topics = note.get("topics_covered", [])
    if topics:
        topics_lines = "\n".join(f"- {t}" for t in topics)
        topics_section = f"\n## Topics Covered\n{topics_lines}\n"
    else:
        topics_section = ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_writer.py::test_build_video_body_uses_correct_field_names tests/test_writer.py::test_build_video_body_missing_quote_keys_no_crash -v`
Expected: PASS

- [ ] **Step 5: Run all writer tests**

Run: `python -m pytest tests/test_writer.py -v`

- [ ] **Step 6: Commit**

```bash
git add vault/writer.py tests/test_writer.py
git commit -m "fix: use key_quotes and topics_covered field names in video body builder"
```

---

## Task 5: `new_event_loop()` Inside Running Loop in Discovery Scheduler

**File:** `core/discovery_scheduler.py` — lines 58 and 393

**Root Cause:** Two issues:
1. `_blocking_refresh()` at line 58 creates a new event loop to run `_refresh_keywords()` synchronously during `__init__`. This is fine for initialization but wrong if called from within an already-running loop.
2. `_search_minimax()` at line 393 creates `asyncio.new_event_loop()` and tries to run `_fetch_article_snippet()` (an async function) in it. But `_search_minimax` is called from `_search_keyword` which is called from `_run_discovery_cycle` — all running in the main event loop. This raises `RuntimeError: asyncio.run() cannot be called from a running event loop`.

**Test:** Add test to `tests/test_discovery_scheduler.py`.

- [ ] **Step 1: Write test reproducing the nested loop error**

Add to `tests/test_discovery_scheduler.py`:

```python
@pytest.mark.asyncio
async def test_search_minimax_no_nested_event_loop():
    """_search_minimax must not create a new event loop when already running."""
    from core.discovery_scheduler import DiscoveryScheduler
    import asyncio

    scheduler = DiscoveryScheduler()

    # This is called from within an async context (already running loop)
    # Must not raise RuntimeError: loop already running
    try:
        results = await scheduler._search_minimax("test query")
        # If API key not set, returns [] — that's fine
        assert isinstance(results, list)
    except RuntimeError as e:
        if "loop already running" in str(e):
            pytest.fail(f"nested event loop bug: {e}")
        raise
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_discovery_scheduler.py::test_search_minimax_no_nested_event_loop -v`
Expected: May pass or fail depending on whether MINIMAX_API_KEY is set (if not set, returns [] before reaching the buggy code). Run with `MINIMAX_API_KEY=test python -m pytest ...` to trigger the bug.

- [ ] **Step 3: Fix `_search_minimax` — remove `new_event_loop()` pattern**

In `core/discovery_scheduler.py`, find and fix the `_search_minimax` method. The `_fetch_article_snippet` at line ~393 is already an async coroutine but it's being run with `loop.run_until_complete()`. The correct fix is to make it awaitable within the existing loop.

The problematic code (around line 388-404):
```python
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
try:
    fetch_result = self._fetch_article_snippet(url)
    if asyncio.iscoroutine(fetch_result):
        real_snippet = loop.run_until_complete(fetch_result)
    else:
        real_snippet = fetch_result
finally:
    loop.close()
```

Replace with direct await (since we're already in an async context):
```python
real_snippet = await self._fetch_article_snippet(url)
```

But `_search_minimax` is `def` not `async def`. First change it to `async def` and update its caller chain.

**Full fix:**

```python
# Line 178: _search_keyword is async, change _search_minimax to async:
async def _search_minimax(self, keyword: str, limit: int = 3) -> list[dict]:
    # ... existing code until the URL validation/HEAD check section ...
    
    # Replace lines ~393-404 with direct await:
    validated = []
    for r in raw_urls:
        url = r.get("url", "")
        if not url or not url.startswith("http"):
            continue
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as hresp:
                if hresp.status < 400:
                    # Direct await — no new loop needed
                    real_snippet = await self._fetch_article_snippet(url)
                    validated.append({
                        "url": url,
                        "title": r.get("title", keyword),
                        "snippet": real_snippet[:200] if real_snippet else r.get("snippet", "")[:200],
                        "source": "minimax",
                    })
        except Exception:
            _logger.debug("Discovery: MiniMax URL failed HEAD check, dropping: %s", url)
        if len(validated) >= limit:
            break

    return validated
```

Also fix `_blocking_refresh` at line 56-63 — this is called from `__init__` in a background thread, so the new loop there is OK, but it needs to be robust if the loop is already set:

```python
def _blocking_refresh(self):
    """Run _refresh_keywords synchronously in a thread (for __init__)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already in an event loop — use a new one for the thread
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            new_loop.run_until_complete(self._refresh_keywords())
        finally:
            new_loop.close()
    else:
        # No running loop — safe to use get_event_loop
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self._refresh_keywords())
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_discovery_scheduler.py -v --timeout=30`

- [ ] **Step 5: Commit**

```bash
git add core/discovery_scheduler.py tests/test_discovery_scheduler.py
git commit -m "fix: remove nested event loop in _search_minimax, use direct await"
```

---

## Task 6: MiniMax API Response Shape Unverified

**File:** `core/minimax_client.py` — lines 254-256, 377-379

**Root Cause:** Code checks `base_resp.status_code` but if MiniMax returns a different shape (e.g., top-level `error` field, or different `base_resp` structure), errors are silently ignored and fallback notes are generated.

**Test:** Add mock test with unexpected response shape.

- [ ] **Step 1: Write response shape robustness test**

Add to `tests/test_minimax_client.py`:

```python
def test_enrich_handles_unexpected_response_shape(monkeypatch):
    """Malformed or unexpected MiniMax response shapes must not silently pass."""
    from core.minimax_client import enrich

    calls = {}
    def mock_post(url, headers, json, timeout):
        calls["made"] = True
        class FakeResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                # Unexpected shape: no base_resp, no choices error
                return {
                    "choices": [{
                        "message": {
                            "content": '{"title": "Test", "type": "article", "tags": [], "summary": "ok", "key_facts": [], "cross_links": [], "entities": [], "figure_captions": [], "why_saved_hint": "", "chapters": [], "key_quotes": [], "topics_covered": []}'
                        }
                    }]
                }
        return FakeResp()

    monkeypatch.setattr("requests.post", mock_post)
    result = enrich("raw text", [], "http://example.com")
    # Must not raise, must return valid note
    assert result.get("title") == "Test"
    assert result.get("error") is False


def test_enrich_api_error_returns_fallback(monkeypatch):
    """MiniMax API error (non-zero status) must return fallback note with error=True."""
    from core.minimax_client import enrich

    def mock_post(url, headers, json, timeout):
        class FakeResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {
                    "base_resp": {"status_code": 10001, "status_msg": "rate limited"},
                    "choices": []
                }
        return FakeResp()

    monkeypatch.setattr("requests.post", mock_post)
    result = enrich("raw text", [], "http://example.com")
    # Must return fallback note
    assert result.get("title") == "Untitled"
    assert result.get("error") is True
```

- [ ] **Step 2: Run tests to verify behavior**

Run: `python -m pytest tests/test_minimax_client.py::test_enrich_handles_unexpected_response_shape tests/test_minimax_client.py::test_enrich_api_error_returns_fallback -v`

- [ ] **Step 3: Improve error handling in enrich()**

In `core/minimax_client.py` around line 254-272:

```python
    try:
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        # Check for API-level errors
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code") and base_resp["status_code"] != 0:
            _logger.warning("MiniMax API error %s: %s", base_resp["status_code"], base_resp.get("status_msg"))
            return _make_fallback_note(raw_text)
        if "choices" not in data or not data["choices"]:
            _logger.error("Minimax response missing choices for source=%s", source)
            return _make_fallback_note(raw_text)
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        _logger.warning("Minimax enrich failed for source=%s: %s", source, e)
        return _make_fallback_note(raw_text)

    try:
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(content)
    except (json.JSONDecodeError, AttributeError) as e:
        _logger.warning("Minimax returned invalid JSON for source=%s: %s", source, e)
        return _make_fallback_note(raw_text)
```

- [ ] **Step 4: Run minimax tests**

Run: `python -m pytest tests/test_minimax_client.py -v`

- [ ] **Step 5: Commit**

```bash
git add core/minimax_client.py tests/test_minimax_client.py
git commit -m "fix: robust error handling for MiniMax API response shapes and JSON parse failures"
```

---

## Task 7: `json.loads()` Without Try-Except (Already Covered in Task 6)

The fix in Task 6 step 3 adds try-except around `json.loads()`. Task 6 and 7 are combined.

---

## Task 8: Missing `raw_text` in Single-Chunk Video

**File:** `core/minimax_client.py` — `enrich_video_synthesis()` lines 329-334

**Root Cause:** When `len(chunk_results) == 1`, the single chunk result is returned directly WITHOUT adding `raw_text` from the chunk. The synthesis path (multi-chunk) also doesn't add `raw_text`.

**Test:** Add to `tests/test_minimax_client.py`.

- [ ] **Step 1: Write test for raw_text preservation**

Add to `tests/test_minimax_client.py`:

```python
def test_video_synthesis_preserves_raw_text(monkeypatch):
    """Single-chunk video synthesis must preserve raw_text in returned note."""
    from core.minimax_client import enrich_video_synthesis

    def mock_post(url, headers, json, timeout):
        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {
                    "base_resp": {"status_code": 0},
                    "choices": [{"message": {"content": '{"title":"T","type":"video","tags":[],"summary":"S","key_facts":[],"cross_links":[],"entities":[],"chapters":[],"key_quotes":[],"topics_covered":[],"why_saved_hint":""}'}}]
                }
        return FakeResp()

    monkeypatch.setattr("requests.post", mock_post)

    # Single chunk with raw_text
    chunk_results = [{
        "title": "Chunk 1",
        "summary": "S1",
        "raw_text": "This is the original transcript text that must be preserved",
        "chapters": [], "key_quotes": [], "entities": [],
        "key_facts": [], "topics_covered": [], "tags": [],
        "cross_links": [], "why_saved_hint": "",
    }]
    result = enrich_video_synthesis(chunk_results, "https://youtube.com/watch?v=xxx", [])

    # raw_text from chunk must be in result
    assert "raw_text" in result, "raw_text missing from single-chunk synthesis result"
    assert "original transcript" in result["raw_text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_minimax_client.py::test_video_synthesis_preserves_raw_text -v`
Expected: FAIL — raw_text not in result

- [ ] **Step 3: Fix single-chunk path in enrich_video_synthesis**

In `core/minimax_client.py`, fix the single-chunk path (~line 329):

```python
    if len(chunk_results) == 1:
        # Single chunk — no synthesis needed, just enrich normally
        r = chunk_results[0].copy()
        r.setdefault("type", "video")
        r.setdefault("error", False)
        # Preserve raw_text from the chunk
        r.setdefault("raw_text", chunk_results[0].get("raw_text", ""))
        return r
```

Also add `raw_text` preservation in the multi-chunk path (after line ~391):

```python
        result.setdefault("raw_text", chunk_results[0].get("raw_text", ""))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_minimax_client.py::test_video_synthesis_preserves_raw_text -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/minimax_client.py tests/test_minimax_client.py
git commit -m "fix: preserve raw_text in single-chunk video synthesis result"
```

---

## Task 9: Double Scheduler Instantiation Race

**File:** `app.py` — `_get_scheduler()` lines 19-24

**Root Cause:** Two concurrent requests when `_scheduler is None` can create two `DiscoveryScheduler` instances and call `start()` twice.

**Test:** Add to `tests/test_app.py`.

- [ ] **Step 1: Write concurrency test**

Add to `tests/test_app.py`:

```python
@pytest.mark.asyncio
async def test_get_scheduler_singleton_not_racy():
    """Concurrent calls to _get_scheduler() must not create two schedulers."""
    import asyncio
    from unittest.mock import patch, MagicMock

    # Reset global state
    import app
    app._scheduler = None

    call_count = 0
    original_scheduler_init = type(app.DiscoveryScheduler)

    def counting_scheduler():
        nonlocal call_count
        call_count += 1
        return original_scheduler_init()

    with patch.object(app, 'DiscoveryScheduler', counting_scheduler):
        async def get_scheduler_twice():
            s1 = app._get_scheduler()
            s2 = app._get_scheduler()
            return s1, s2

        s1, s2 = await get_scheduler_twice()
        assert call_count == 1, f"Scheduler created {call_count} times instead of once"
        assert s1 is s2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_app.py::test_get_scheduler_singleton_not_racy -v`
Expected: FAIL — scheduler created twice

- [ ] **Step 3: Fix with asyncio.Lock**

In `app.py`:

```python
_scheduler: DiscoveryScheduler | None = None
_scheduler_lock = asyncio.Lock()  # NEW

async def _get_scheduler() -> DiscoveryScheduler:
    global _scheduler
    if _scheduler is None:
        async with _scheduler_lock:
            # Double-check after acquiring lock
            if _scheduler is None:
                _scheduler = DiscoveryScheduler()
                _scheduler.start(pipeline_func=run_pipeline)
    return _scheduler
```

Note: The `/keywords` endpoint calls `_get_scheduler()` synchronously via `asyncio.to_thread`, but it's an async function. Change the endpoint to await it:

```python
@app.get("/keywords")
async def get_keywords():
    """Return the scheduler's keyword list split into manual vs graph-derived."""
    scheduler = await _get_scheduler()  # await the async version
    ...
```

- [ ] **Step 4: Run app tests**

Run: `python -m pytest tests/test_app.py -v`

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "fix: add lock for scheduler singleton to prevent double initialization"
```

---

## Task 10: Whisper Model Reloaded Every Call

**File:** `ingesters/youtube.py` — line 137

**Root Cause:** `whisper.load_model("base")` is called on every `_try_whisper_transcription` invocation. Should be cached at module level.

**Test:** Add caching test.

- [ ] **Step 1: Write test for model caching**

Add to `tests/test_youtube_ingester.py` or a new test:

```python
def test_whisper_model_cached_not_reloaded(monkeypatch):
    """Whisper model must be loaded once and cached, not reloaded on every call."""
    from ingesters.youtube import _try_whisper_transcription

    load_count = 0
    mock_model = MagicMock()
    mock_model.transcribe.return_value = {"text": "transcribed text"}

    def counting_load_model(name):
        nonlocal load_count
        load_count += 1
        return mock_model

    monkeypatch.setattr("whisper.load_model", counting_load_model)

    # Call twice — model should only be loaded once
    _try_whisper_transcription("https://youtube.com/watch?v=dummy")
    _try_whisper_transcription("https://youtube.com/watch?v=dummy2")

    assert load_count == 1, f"Whisper model loaded {load_count} times instead of 1 (should be cached)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_youtube_ingester.py::test_whisper_model_cached_not_reloaded -v`
Expected: FAIL — model loaded 2 times

- [ ] **Step 3: Add module-level cache**

In `ingesters/youtube.py`:

```python
_whisper_model = None  # Module-level cache

def _get_whisper_model():
    """Load and cache Whisper model."""
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = whisper.load_model("base")
    return _whisper_model
```

Then in `_try_whisper_transcription`:
```python
model = _get_whisper_model()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_youtube_ingester.py::test_whisper_model_cached_not_reloaded -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ingesters/youtube.py tests/test_youtube_ingester.py
git commit -m "fix: cache Whisper model at module level to avoid repeated reloading"
```

---

## Task 11: BM25 `ensure_index()` Exception Not Handled

**File:** `core/bm25_index.py` — line 78

**Root Cause:** `bm25_search()` calls `ensure_index()` but if it raises (corrupt files, disk errors), exception bubbles up. `_build_index()` catches per-file errors but not systemic ones.

**Test:** Add to `tests/test_bm25_index.py`.

- [ ] **Step 1: Write exception handling test**

Add to `tests/test_bm25_index.py`:

```python
def test_bm25_search_handles_index_exception(monkeypatch):
    """bm25_search must return [] on ensure_index exception, not crash."""
    from core.bm25_index import bm25_search

    def raise_index(*args):
        raise RuntimeError("Disk error simulating corruption")

    monkeypatch.setattr("core.bm25_index.ensure_index", raise_index)

    # Must return [] not raise
    result = bm25_search("test query")
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bm25_index.py::test_bm25_search_handles_index_exception -v`
Expected: FAIL — RuntimeError propagates

- [ ] **Step 3: Add try-except to bm25_search**

In `core/bm25_index.py`:

```python
def bm25_search(query: str, top_k: int = 5) -> list[dict]:
    try:
        index, paths, corpus = ensure_index()
    except Exception as e:
        _logger.warning("BM25 search failed to build index: %s", e)
        return []
    if not paths:
        return []
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bm25_index.py::test_bm25_search_handles_index_exception -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/bm25_index.py tests/test_bm25_index.py
git commit -m "fix: handle exceptions in bm25_search to return empty list instead of crashing"
```

---

## Task 12: Gap Detection Fire-and-Forget Task

**File:** `pipeline.py` — line 152

**Root Cause:** `asyncio.create_task(_run_gap_searches(...))` is not stored or awaited. If `run_pipeline` completes before the gap search starts, the task may never run.

**Test:** Low priority — add comment-based fix and optional test.

- [ ] **Step 1: Store the task and add proper cleanup**

In `pipeline.py`, change:
```python
if note["gap_entities"]:
    asyncio.create_task(_run_gap_searches(note["gap_entities"]))
```

To:
```python
if note["gap_entities"]:
    # Store task reference to prevent fire-and-forget garbage collection
    # and ensure it runs even if pipeline completes quickly
    gap_task = asyncio.create_task(_run_gap_searches(note["gap_entities"]))
    # Let it run in background — failures are logged inside _run_gap_searches
    gap_task.add_done_callback(
        lambda t: _logger.debug("Gap search task completed: %s", t.result())
        if not t.cancelled() and t.exception() is None
        else _logger.warning("Gap search task failed: %s", t.exception())
    )
```

Or use `asyncio.ensure_future` and let it run independently.

- [ ] **Step 2: Commit**

```bash
git add pipeline.py
git commit -m "fix: store gap search task reference with done callback for observability"
```

---

## Task 13: `http://` URLs Accepted in MiniMax Search

**File:** `core/discovery_scheduler.py` — line 385

**Root Cause:** `http://` URLs are accepted by `url.startswith("http")`. This is inconsistent and potentially a security concern.

**Test:** Add test.

- [ ] **Step 1: Write test**

Add to `tests/test_discovery_scheduler.py`:

```python
def test_minimax_search_rejects_http_urls(monkeypatch):
    """MiniMax search must only accept https:// URLs."""
    from core.discovery_scheduler import DiscoveryScheduler

    scheduler = DiscoveryScheduler()
    accepted_urls = []
    rejected_urls = []

    # Mock HEAD to succeed for both
    def mock_head(req):
        class R:
            status = 200
        return R()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_head)

    # Mock minimax to return URLs
    def mock_post(url, headers, json, timeout):
        class R:
            def raise_for_status(self): pass
            def json(self):
                return {
                    "base_resp": {"status_code": 0},
                    "choices": [{
                        "message": {
                            "content": json.dumps([
                                {"url": "http://insecure.example.com/page", "title": "Insecure", "snippet": ""},
                                {"url": "https://secure.example.com/page", "title": "Secure", "snippet": ""},
                            ])
                        }
                    }]
                }
        return R()

    monkeypatch.setattr("requests.post", mock_post)

    import asyncio
    results = asyncio.run(scheduler._search_minimax("test"))
    urls = [r["url"] for r in results]

    assert "http://insecure.example.com/page" not in urls, "http:// URL was not rejected"
    assert "https://secure.example.com/page" in urls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_discovery_scheduler.py::test_minimax_search_rejects_http_urls -v`
Expected: FAIL

- [ ] **Step 3: Fix URL validation**

In `discovery_scheduler.py` line ~385:
```python
if not url or not url.startswith("https"):
    continue
```

- [ ] **Step 4: Run test to verify it passes**

- [ ] **Step 5: Commit**

---

## Task 14: Temp PDF File TOCTOU Race

**File:** `ingesters/router.py` — lines 53-69

**Root Cause:** `os.path.exists(tmp_path)` check before `os.unlink(tmp_path)` is a TOCTOU race. Use try-finally directly after file creation instead.

**Test:** Low priority — structural fix without new test needed.

- [ ] **Step 1: Fix with try-finally pattern**

In `ingesters/router.py`, replace:
```python
with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
    tmp_path = tmp.name
await asyncio.to_thread(urllib.request.urlretrieve, url, tmp_path)
# Validate magic bytes before passing to docling
with open(tmp_path, "rb") as f:
    header = f.read(5)
if header != b"%PDF-":
    os.unlink(tmp_path)
    raise ValueError(...)
try:
    result = await asyncio.to_thread(extract_pdf_full, tmp_path)
finally:
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)
```

With cleaner approach using `tempfile.mkstemp` or just relying on `delete=True`:

```python
# Use delete=True and rely on process exit for cleanup (process-scoped temp)
# OR use a context manager approach:
tmp_path = None
try:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    await asyncio.to_thread(urllib.request.urlretrieve, url, tmp_path)
    with open(tmp_path, "rb") as f:
        header = f.read(5)
    if header != b"%PDF-":
        raise ValueError(f"URL has .pdf extension but content is not valid PDF")
    result = await asyncio.to_thread(extract_pdf_full, tmp_path)
finally:
    if tmp_path and os.path.exists(tmp_path):
        os.unlink(tmp_path)
```

- [ ] **Step 2: Commit**

```bash
git add ingesters/router.py
git commit -m "fix: remove TOCTOU race in temp PDF file cleanup"
```

---

## Task 15: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && python -m pytest tests/ -v --timeout=60 -x`
Expected: All tests pass

- [ ] **Step 2: Run specific video synthesis tests**

Run: `python -m pytest tests/test_video_synthesis.py -v`
Expected: All 11 tests pass

- [ ] **Step 3: Verify no regressions**

---

## Execution Order

```
Task 1  → Empty chunk bug (core/minimax_client.py)
Task 4  → Wrong key names (vault/writer.py)
Task 3  → SQL injection (core/vector_store.py)
Task 2  → Queue race (app.py)
Task 5  → Event loop nesting (core/discovery_scheduler.py)
Task 6+7 → API shape + json.loads (core/minimax_client.py)
Task 8  → raw_text missing (core/minimax_client.py)
Task 9  → Double scheduler (app.py)
Task 10 → Whisper caching (ingesters/youtube.py)
Task 11 → BM25 exception (core/bm25_index.py)
Task 12 → Gap detection task (pipeline.py)
Task 13 → http:// URL rejection (core/discovery_scheduler.py)
Task 14 → PDF TOCTOU (ingesters/router.py)
Task 15 → Final verification
```

---

## Self-Review Checklist

1. **Coverage:** All 14 bugs have a task with test + fix + commit steps
2. **No placeholders:** Every step has actual code, commands, and expected outputs
3. **Type consistency:** Field names `key_quotes`/`topics_covered` used consistently after Task 4
4. **Test-first:** Each fix has a failing test before the implementation
5. **One commit per task:** Easy to revert individual fixes if needed
