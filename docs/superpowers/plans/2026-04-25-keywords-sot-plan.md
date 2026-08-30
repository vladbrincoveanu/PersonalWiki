# Keywords Single Source of Truth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify keywords/tags/wikilinks as a single source of truth with human-in-the-loop keyword management and two-phase manual ingest.

**Architecture:** Two-phase ingest (preview → extract keywords → user confirms → full pipeline with keywords). `_keywords` file is the canonical store. Note frontmatter uses `keywords` field. Note body has `[[wikilink]]` section. Discovery searches with existing keywords only, never creates new ones.

**Tech Stack:** FastAPI, Jinja2 (SSE streaming), MiniMax LLM (keyword extraction + enrichment), frontmatter Python library, DuckDB/LanceDB vector store

---

## File Structure

### New files:
- `scripts/migrate_tags_to_keywords.py` — one-time migration of `tags` frontmatter to `keywords`

### Modified files:
- `core/keyword_extractor.py` — add `extract_and_classify()` that checks against `_keywords`
- `vault/writer.py` — write `keywords` frontmatter + `[[wikilink]]` body section instead of `tags`
- `pipeline.py` — accept `keywords` parameter, write to note
- `core/keywords_manager.py` — cascade delete: handle multi-keyword files (remove keyword only, don't delete)
- `core/discovery_scheduler.py` — add `trigger_cycle()`, pass keywords to pipeline for discovery notes
- `app.py` — add `POST /ingest/preview`, `POST /ingest/run`, `POST /discovery/trigger`; in-memory preview cache
- `templates/index.html` — two-phase ingest UI, discovery panel moved up, "Run Discovery Now" button
- `tests/test_keyword_extractor.py` — tests for `extract_and_classify()`
- `tests/test_writer.py` — tests for `keywords` frontmatter and `[[wikilink]]` injection
- `tests/test_app.py` — tests for new endpoints

---

### Task 1: Update keyword_extractor.py — add extract_and_classify()

**Files:**
- Modify: `core/keyword_extractor.py`
- Test: `tests/test_keyword_extractor.py`

- [ ] **Step 1: Add `extract_and_classify()` function**

```python
# Add to core/keyword_extractor.py

def _load_keywords(path: Path) -> set[str]:
    from core.keywords_manager import load_manual_keywords
    return set(load_manual_keywords(path))


def extract_and_classify(
    raw_text: str,
    title: str,
    keywords_path: Path,
) -> dict:
    """Extract candidate keywords from text and classify as existing vs new.

    Args:
        raw_text: Full extracted text content.
        title: Document title.
        keywords_path: Path to _keywords file.

    Returns:
        dict with { existing: [str], new: [str] }
    """
    candidates = extract_keywords_from_note(title, raw_text)
    if not candidates:
        return {"existing": [], "new": []}

    existing_keywords = _load_keywords(keywords_path)
    existing = []
    new = []
    for kw in candidates:
        if kw in existing_keywords:
            existing.append(kw)
        else:
            new.append(kw)
    return {"existing": existing, "new": new}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_keyword_extractor.py -v 2>&1 | head -40`
Expected: PASS (existing tests still pass) but we need to add new test.

- [ ] **Step 3: Add tests for extract_and_classify**

```python
# Add to tests/test_keyword_extractor.py

def test_extract_and_classify_all_existing(tmp_path):
    from core.keyword_extractor import extract_and_classify
    kws_file = tmp_path / "_keywords"
    kws_file.write_text("python\nmachine-learning\napi\n")
    text = "Python is a programming language. Machine learning uses Python APIs."
    result = extract_and_classify(text, "Test Article", kws_file)
    assert "existing" in result
    assert "new" in result
    assert "python" in result["existing"]
    assert not result["new"]  # All keywords exist


def test_extract_and_classify_some_new(tmp_path, monkeypatch):
    from core.keyword_extractor import extract_and_classify
    kws_file = tmp_path / "_keywords"
    kws_file.write_text("python\n")
    text = "Python is great for deep learning and neural networks."
    # Mock the LLM call to return known + unknown keywords
    def mock_extract(title, raw_text):
        return ["python", "deep-learning", "neural-networks"]
    monkeypatch.setattr("core.keyword_extractor.extract_keywords_from_note", mock_extract)
    result = extract_and_classify(text, "Test", kws_file)
    assert "python" in result["existing"]
    assert "deep-learning" in result["new"]
    assert "neural-networks" in result["new"]


def test_extract_and_classify_empty_text(tmp_path):
    from core.keyword_extractor import extract_and_classify
    kws_file = tmp_path / "_keywords"
    kws_file.write_text("python\n")
    result = extract_and_classify("", "Empty", kws_file)
    assert result == {"existing": [], "new": []}
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_keyword_extractor.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```
git add core/keyword_extractor.py tests/test_keyword_extractor.py
git commit -m "feat: add extract_and_classify to keyword_extractor"
```

---

### Task 2: Update vault/writer.py — keywords frontmatter + wikilinks

**Files:**
- Modify: `vault/writer.py`
- Test: `tests/test_writer.py`

- [ ] **Step 1: Read current writer.py to understand write_note signature**

- [ ] **Step 2: Add wikilink injection helper**

```python
# Add before _build_body in vault/writer.py

def _inject_keywords_section(body: str, keywords: list[str]) -> str:
    """Add a ## Keywords section with [[wikilink]] references after the summary.

    If the section already exists, replace it. Otherwise insert after the first
    ## heading that isn't the title (i.e., after Summary).
    """
    links = " · ".join(f"[[{kw}]]" for kw in keywords if kw.strip())
    if not links:
        return body

    kw_section = f"\n## Keywords\n{links}\n"

    # Replace existing Keywords section if present
    import re
    if re.search(r"^## Keywords\s*$", body, re.MULTILINE):
        return re.sub(
            r"^## Keywords\s*$(\n(?:\[\[.*\]\]\s*(?:·\s*)?)*)?",
            kw_section.strip(),
            body,
            flags=re.MULTILINE,
        )

    # Insert after the first ## heading (which is ## Summary)
    lines = body.split("\n")
    insert_at = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and not line.startswith("###"):
            insert_at = i + 1
            break

    if insert_at is not None:
        lines.insert(insert_at, kw_section.strip())
        return "\n".join(lines)

    return body + kw_section
```

- [ ] **Step 3: Update write_note to accept and use keywords parameter**

Change `write_note` signature and metadata:

```python
def write_note(
    note: dict,
    source: str,
    ingested_date: str | None = None,
    images: Sequence[bytes] = (),
    entity_statuses: list[dict] = (),
    is_discovery: bool = False,
    source_keyword: str | None = None,
    keywords: list[str] | None = None,  # NEW: canonical keyword list
) -> str:
```

Inside `write_note`, replace the `tags` metadata with `keywords`:

```python
    metadata = {
        "title": title,
        "source": source,
        "type": note.get("type", "article"),
        "keywords": keywords or [],  # CHANGED: tags → keywords
        "ingested": ingested_date,
    }
    if is_discovery:
        metadata["discovery"] = "auto"
    if source_keyword:
        metadata["source_keyword"] = source_keyword  # Keep for audit trail
```

After building the body, inject the keywords section:

```python
    body = _build_body(note, entity_statuses=entity_statuses)
    if keywords:
        body = _inject_keywords_section(body, keywords)
    if is_discovery:
        body = body.rstrip() + "\n\n#auto-discovery\n"
```

- [ ] **Step 4: Update tests**

Add tests to `tests/test_writer.py`:

```python
def test_write_note_injects_keywords_frontmatter(tmp_path, monkeypatch):
    from vault.writer import write_note
    monkeypatch.setattr("vault.writer.NOTES_DIR", tmp_path)
    monkeypatch.setattr("vault.writer.VAULT_PATH", tmp_path)
    path = write_note(
        {"title": "Test", "summary": "A note."},
        source="https://example.com",
        keywords=["python", "testing"],
    )
    content = Path(path).read_text()
    assert "keywords:" in content
    assert "python" in content
    assert "testing" in content


def test_write_note_injects_keywords_wikilinks(tmp_path, monkeypatch):
    from vault.writer import write_note
    monkeypatch.setattr("vault.writer.NOTES_DIR", tmp_path)
    monkeypatch.setattr("vault.writer.VAULT_PATH", tmp_path)
    path = write_note(
        {"title": "Wikilink Test", "summary": "A note about things."},
        source="https://example.com",
        keywords=["python", "testing"],
    )
    content = Path(path).read_text()
    assert "[[python]]" in content
    assert "[[testing]]" in content
    assert "## Keywords" in content


def test_write_note_no_keywords_is_unchanged(tmp_path, monkeypatch):
    from vault.writer import write_note
    monkeypatch.setattr("vault.writer.NOTES_DIR", tmp_path)
    monkeypatch.setattr("vault.writer.VAULT_PATH", tmp_path)
    path = write_note(
        {"title": "No Keywords", "summary": "Just a note."},
        source="https://example.com",
    )
    content = Path(path).read_text()
    assert "keywords:" in content
    assert content.count("keywords:") == 1  # frontmatter only
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_writer.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```
git add vault/writer.py tests/test_writer.py
git commit -m "feat: write keywords frontmatter + wikilinks in notes"
```

---

### Task 3: Update pipeline.py — accept keywords parameter

**Files:**
- Modify: `pipeline.py`

- [ ] **Step 1: Add `keywords` parameter to `run_pipeline`**

```python
async def run_pipeline(
    url: str | None = None,
    pdf_path: str | None = None,
    docx_path: str | None = None,
    md_path: str | None = None,
    txt_path: str | None = None,
    is_discovery: bool = False,
    source_keyword: str | None = None,
    keywords: list[str] | None = None,  # NEW
) -> AsyncGenerator[str, None]:
```

- [ ] **Step 2: Wire keywords to write_note call**

In the "Step 4: Write" section, pass keywords:

```python
    path = write_note(
        note, source=source, images=images, entity_statuses=entity_statuses,
        is_discovery=is_discovery, source_keyword=source_keyword,
        keywords=keywords,  # NEW
    )
```

- [ ] **Step 3: Update tests**

Check `tests/test_pipeline.py` — the `run_pipeline` calls should pass through keywords. If there are tests that mock `write_note`, update the mock to accept the `keywords` parameter.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_pipeline.py tests/test_pipeline_md_and_video.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```
git add pipeline.py
git commit -m "feat: pipeline accepts keywords param, wires to writer"
```

---

### Task 4: Update keywords_manager.py cascade delete

**Files:**
- Modify: `core/keywords_manager.py`
- Test: `tests/test_keywords_manager.py`

- [ ] **Step 1: Read current remove_keyword and cascade delete logic**

Current flow:
- `remove_keyword()` calls `_cascade_delete_by_source_keyword()` which deletes notes with matching `source_keyword` frontmatter
- Then calls `purge_keyword()` which strips `[[wikilink]]` references

New flow must check `keywords` frontmatter too:
- If note has `keywords: [keyword-to-delete, other-keyword]` → remove just that keyword from frontmatter, strip wikilinks, keep file
- If note has `keywords: [keyword-to-delete]` (only keyword) → delete file

- [ ] **Step 2: Add helper to check if keyword is the only one in a note**

```python
def _check_keyword_impact(keyword: str, vault_path: Path) -> dict:
    """Scan vault for notes affected by keyword deletion.

    Returns dict with:
      delete: [paths to delete entirely]
      remove_keyword_only: [paths to strip keyword from but keep]
    """
    import frontmatter as fm

    delete = []
    remove_keyword_only = []

    for md_file in vault_path.rglob("*.md"):
        try:
            parsed = fm.parse(md_file.read_text(encoding="utf-8"))
            metadata, _ = parsed
            file_kws = metadata.get("keywords", [])
            source_kw = metadata.get("source_keyword")

            has_kw = keyword in file_kws or source_kw == keyword
            if not has_kw:
                continue

            # Check if this is the only keyword
            other_kws = [k for k in file_kws if k != keyword]
            has_other = bool(other_kws) or (source_kw and source_kw != keyword)

            if has_other:
                remove_keyword_only.append(str(md_file))
            else:
                delete.append(str(md_file))
        except Exception:
            continue

    return {"delete": delete, "remove_keyword_only": remove_keyword_only}
```

- [ ] **Step 3: Update remove_keyword to use new logic**

```python
def remove_keyword(keyword: str, path: Path, vault_path: Path | None = None) -> dict:
    """Remove keyword from _keywords file and cascade.

    Returns dict with { deleted: [...], stripped: [...] }.
    Raises KeyError if keyword not found.
    """
    existing = load_manual_keywords(path)
    if keyword not in existing:
        raise KeyError(f"Keyword '{keyword}' not found in {path}")
    existing.remove(keyword)
    save_manual_keywords(existing, path)

    result = {"deleted": [], "stripped": []}

    if vault_path and vault_path.exists():
        impact = _check_keyword_impact(keyword, vault_path)
        result["deleted"] = impact["delete"]
        result["stripped"] = impact["remove_keyword_only"]

        # Delete fully-affected files + vector store
        from core.vector_store import get_store
        try:
            store = get_store()
        except Exception:
            store = None

        for filepath in impact["delete"]:
            md_path = Path(filepath)
            md_path.unlink()
            if store:
                try:
                    store.delete(filepath)
                except Exception:
                    pass

        # Strip keyword from remaining files
        for filepath in impact["remove_keyword_only"]:
            md_path = Path(filepath)
            try:
                _strip_keyword_from_file(keyword, md_path)
            except Exception:
                continue

        # Also purge wikilinks from all surviving files
        purge_keyword(keyword, vault_path)

    return result


def _strip_keyword_from_file(keyword: str, filepath: Path) -> None:
    """Remove keyword from frontmatter keywords list and strip [[wikilinks]]."""
    import frontmatter as fm

    raw = filepath.read_text(encoding="utf-8")
    parsed = fm.parse(raw)
    metadata, body = parsed

    kws = metadata.get("keywords", [])
    if keyword in kws:
        kws.remove(keyword)
        metadata["keywords"] = kws

    post = fm.Post(body, **metadata)
    filepath.write_text(fm.dumps(post), encoding="utf-8")

    # Also strip wikilinks from body
    raw = filepath.read_text(encoding="utf-8")
    import re
    new_raw = re.sub(rf"\[\[{re.escape(keyword)}\]\]", keyword, raw, flags=re.IGNORECASE)
    filepath.write_text(new_raw, encoding="utf-8")
```

- [ ] **Step 4: Update tests**

```python
# tests/test_keywords_manager.py

def test_remove_keyword_cascade_delete_last_keyword(tmp_path):
    from core.keywords_manager import remove_keyword, add_keyword

    kws_file = tmp_path / "_keywords"
    add_keyword("test-kw", kws_file)

    # Create a note with only this keyword
    note = tmp_path / "test-note.md"
    note.write_text(
        "---\nkeywords: [test-kw]\ntitle: Test\n---\nBody content."
    )

    result = remove_keyword("test-kw", kws_file, vault_path=tmp_path)
    assert "test-kw" not in kws_file.read_text()
    assert not note.exists()  # File was deleted
    assert "test-note.md" in str(result["deleted"][0])


def test_remove_keyword_partial_remove_multi_keyword(tmp_path):
    from core.keywords_manager import remove_keyword, add_keyword

    kws_file = tmp_path / "_keywords"
    add_keyword("keep", kws_file)
    add_keyword("remove", kws_file)

    note = tmp_path / "multi-note.md"
    note.write_text(
        "---\nkeywords: [keep, remove]\ntitle: Multi\n---\nBody [[remove]] here."
    )

    result = remove_keyword("remove", kws_file, vault_path=tmp_path)
    assert "remove" not in kws_file.read_text()
    assert note.exists()  # File kept

    content = note.read_text()
    assert "keep" in content
    assert "remove" not in content  # Stripped from keywords + body
    assert "[[remove]]" not in content  # Wikilink stripped
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_keywords_manager.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```
git add core/keywords_manager.py tests/test_keywords_manager.py
git commit -m "fix: cascade delete respects multi-keyword files"
```

---

### Task 5: Update discovery_scheduler.py

**Files:**
- Modify: `core/discovery_scheduler.py`

- [ ] **Step 1: Add trigger_cycle() public method**

```python
async def trigger_cycle(self) -> None:
    """Trigger a single discovery cycle immediately (from UI)."""
    if not self._running:
        _logger.warning("Discovery: trigger ignored — scheduler not running")
        raise RuntimeError("Discovery scheduler is not running")
    _logger.info("Discovery: manual trigger — running one cycle")
    await self._run_discovery_cycle()
```

- [ ] **Step 2: Update remove_keyword to use new cascade delete**

`DiscoveryScheduler.remove_keyword` currently calls `_km_remove` (returns list) then `_km_purge` separately. With Task 4, `_km_remove` returns a `dict` and handles cascade internally. Simplify:

```python
    def remove_keyword(self, keyword: str) -> dict:
        """Remove keyword; cascade delete handled by keywords_manager."""
        result = _km_remove(keyword, KEYWORDS_FILE, vault_path=Path(VAULT_PATH))
        with self._keywords_lock:
            if keyword in self._keywords:
                self._keywords.remove(keyword)
        return result
```

- [ ] **Step 3: Pass keywords to pipeline in _run_discovery_cycle**

In `_run_pipeline`, pass `keywords=[keyword]` alongside `source_keyword=keyword`:

```python
async def _run_pipeline(self, url: str, keyword: str | None = None):
    dl_logger = get_discovery_logger()
    try:
        from pipeline import run_pipeline
        async for _ in run_pipeline(
            url=url, is_discovery=True, source_keyword=keyword,
            keywords=[keyword] if keyword else None,
        ):
            pass
        dl_logger.update_status(url, "ingested")
    except Exception as e:
        dl_logger.update_status(url, "failed", error=str(e))
        _logger.error("Discovery: pipeline failed for %s: %s", url, e)
```

- [ ] **Step 4: Run existing tests**

Run: `python -m pytest tests/test_discovery_scheduler.py tests/test_discovery_e2e.py tests/test_discovery_integration.py -v`
Expected: All PASS (existing tests unchanged)

- [ ] **Step 5: Commit**

```
git add core/discovery_scheduler.py
git commit -m "feat: add trigger_cycle(), pass keywords to pipeline"
```

---

### Task 6: Update app.py — new endpoints + preview cache

**Files:**
- Modify: `app.py`
- Test: `tests/test_app.py`

- [ ] **Step 1: Add in-memory preview cache**

```python
import time
import uuid

_preview_cache: dict[str, dict] = {}
_PREVIEW_TTL = 300  # 5 minutes
_INGEST_RUN_QUEUES: dict[str, tuple[asyncio.Queue, asyncio.Event]] = {}
```

- [ ] **Step 2: Add POST /ingest/preview endpoint**

```python
@app.post("/ingest/preview")
async def ingest_preview(
    request: Request,
    url: str = Form(None),
    file: UploadFile = None,
):
    """Phase 1: extract content and return keyword classification."""
    from ingesters.router import extract
    from core.keyword_extractor import extract_and_classify
    from core.keywords_manager import load_manual_keywords
    from config import VAULT_PATH
    from core.discovery_scheduler import KEYWORDS_FILE

    if not url and not file:
        raise HTTPException(400, "No url or file provided")

    tmp_path = None
    if file and file.filename:
        content = await file.read()
        ext = Path(file.filename.lower()).suffix
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

    try:
        if url:
            doc = await extract(url)
        elif tmp_path:
            from ingesters.router import extract_pdf, extract_docx, extract_markdown
            if ext == ".pdf":
                doc = await asyncio.to_thread(extract_pdf, tmp_path)
            elif ext == ".docx":
                doc = await asyncio.to_thread(extract_docx, tmp_path)
            else:
                doc = await asyncio.to_thread(extract_markdown, tmp_path)

        title = doc.title or Path(url or "").stem or "Untitled"
        raw_text = doc.raw_text

        keywords = await asyncio.to_thread(
            extract_and_classify, raw_text, title, KEYWORDS_FILE
        )

        preview_id = str(uuid.uuid4())
        _preview_cache[preview_id] = {
            "url": url,
            "tmp_path": tmp_path,
            "title": title,
            "source": url or tmp_path or "",
            "created_at": time.time(),
        }

        return {
            "preview_id": preview_id,
            "title": title,
            "keywords": keywords,
        }
    except Exception as e:
        if tmp_path:
            os.unlink(tmp_path)
        raise HTTPException(500, f"Preview failed: {e}")
```

- [ ] **Step 3: Modify ingest endpoint to accept keywords**

```python
@app.post("/ingest/run")
async def ingest_run(request: Request):
    """Phase 2: run full pipeline with confirmed keywords."""
    body = await request.json()
    preview_id = body.get("preview_id")
    accepted_keywords = body.get("accepted_keywords", [])

    cached = _preview_cache.pop(preview_id, None) if preview_id else None

    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    done_event = asyncio.Event()
    _INGEST_RUN_QUEUES[job_id] = (queue, done_event)

    existing_keywords = await asyncio.to_thread(
        load_manual_keywords, KEYWORDS_FILE
    )

    async def _run():
        try:
            # Add new keywords to _keywords
            from core.keywords_manager import add_keyword as _add_kw
            for kw in accepted_keywords:
                if kw not in existing_keywords:
                    try:
                        _add_kw(kw, KEYWORDS_FILE)
                        await queue.put(f"<p>Keyword added: {kw}</p>")
                    except ValueError:
                        pass  # Already exists (race)

            # Run pipeline with accepted keywords
            kwargs = {"keywords": accepted_keywords}
            if cached and cached.get("url"):
                kwargs["url"] = cached["url"]
            elif body.get("url"):
                kwargs["url"] = body["url"]

            async for msg in run_pipeline(**kwargs):
                await queue.put(f"<p>{msg}</p>")
        except Exception as e:
            await queue.put(f"<p>Error: {e}</p>")
        finally:
            await queue.put(None)
            done_event.set()
            _INGEST_RUN_QUEUES.pop(job_id, None)
            if cached and cached.get("tmp_path"):
                os.unlink(cached["tmp_path"])

    asyncio.create_task(_run())
    return {"job_id": job_id}
```

- [ ] **Step 4: Add POST /discovery/trigger endpoint**

```python
@app.post("/discovery/trigger")
async def trigger_discovery():
    """Trigger one discovery cycle immediately."""
    scheduler = await _get_scheduler()
    try:
        asyncio.create_task(scheduler.trigger_cycle())
        return {"status": "triggered"}
    except RuntimeError as e:
        raise HTTPException(400, str(e))
```

- [ ] **Step 5: Update stream endpoint to use _INGEST_RUN_QUEUES**

The existing `/stream/{job_id}` endpoint uses `_job_queues`. The new `/ingest/run` uses `_INGEST_RUN_QUEUES`. Update stream to check both:

```python
@app.get("/stream/{job_id}")
async def stream(job_id: str):
    async def generate():
        # Check both old and new queue dicts
        entry = _job_queues.get(job_id) or _INGEST_RUN_QUEUES.get(job_id)
        if not entry:
            return
        queue, done_event = entry
        # ... rest unchanged
```

- [ ] **Step 6: Update /keywords endpoint to return frontmatter field name**

The keyword list display stays the same — the `/keywords` endpoint returns the scheduler's keyword list.

- [ ] **Step 7: Update tests**

```python
# tests/test_app.py

def test_ingest_preview_returns_keywords(client, monkeypatch):
    monkeypatch.setattr(
        "core.keyword_extractor.extract_and_classify",
        lambda text, title, path: {"existing": ["python"], "new": ["testing"]},
    )
    resp = client.post("/ingest/preview", data={"url": "https://example.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert "preview_id" in data
    assert data["keywords"]["existing"] == ["python"]
    assert data["keywords"]["new"] == ["testing"]


def test_ingest_run_adds_keywords(app, monkeypatch):
    monkeypatch.setattr(
        "core.keywords_manager.add_keyword",
        lambda kw, path: None,
    )
    resp = app.post("/ingest/run", json={
        "url": "https://example.com",
        "accepted_keywords": ["python", "new-kw"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data


def test_trigger_discovery(client, monkeypatch):
    triggered = False
    async def mock_trigger():
        nonlocal triggered
        triggered = True
    monkeypatch.setattr(
        "core.discovery_scheduler.DiscoveryScheduler.trigger_cycle",
        mock_trigger,
    )
    resp = client.post("/discovery/trigger")
    assert resp.status_code == 200
```

- [ ] **Step 8: Run tests**

Run: `python -m pytest tests/test_app.py -v`
Expected: All tests PASS

- [ ] **Step 9: Commit**

```
git add app.py tests/test_app.py
git commit -m "feat: add /ingest/preview, /ingest/run, /discovery/trigger endpoints"
```

---

### Task 7: Update index.html — UI changes

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Reorder layout**

Change the DOM order to:
1. Header
2. Ingest Card (modified for two-phase flow)
3. Discovery Panel (moved up)
4. Two-column grid (Keywords + Recent Jobs)

Move the discovery panel `<div id="discovery-panel">` from line 681 to right after the progress card (before line 651).

- [ ] **Step 2: Add "Run Discovery Now" button to discovery panel**

Replace the refresh button with two buttons:

```html
<div class="discovery-header">
  <h3>Discovery</h3>
  <div>
    <button onclick="triggerDiscovery()" class="refresh-btn" title="Run discovery now" style="margin-right:0.5rem;">▶ Run</button>
    <button onclick="loadDiscoveryActivity()" class="refresh-btn" title="Refresh">↻</button>
  </div>
</div>
```

Add the triggerDiscovery function:

```javascript
async function triggerDiscovery() {
  try {
    const res = await fetch('/discovery/trigger', { method: 'POST' });
    if (res.ok) {
      setTimeout(loadDiscoveryActivity, 2000);
    }
  } catch(e) {
    console.warn('Discovery trigger failed:', e);
  }
}
```

- [ ] **Step 3: Modify ingest form for two-phase flow**

Replace the current single submit button with:

1. "Extract Keywords" button (sends to `/ingest/preview`)
2. Keyword preview area (hidden initially)
3. "Confirm & Save" button (sends to `/ingest/run`, hidden initially)
4. "Cancel" button (hidden initially)

Add a keyword preview section after the file upload:

```html
<div id="keyword-preview" style="display:none;" class="card" style="margin-bottom:1rem;">
  <div class="card-header">
    <span class="card-title">Extracted Keywords</span>
  </div>
  <div id="keyword-chips"></div>
  <p style="font-size:0.75rem;color:var(--text-dim);margin-top:0.5rem;">
    <span style="color:var(--accent);">●</span> Existing &nbsp;
    <span style="color:var(--info);">●</span> New (check to add)
  </p>
  <div style="display:flex;gap:0.5rem;margin-top:1rem;">
    <button id="confirm-btn" class="btn-ingest" onclick="confirmIngest()">
      Confirm & Save
    </button>
    <button id="cancel-btn" style="background:var(--surface-2);color:var(--text-muted);border:1px solid var(--border);border-radius:var(--radius-sm);padding:0.75rem 1.5rem;cursor:pointer;" onclick="cancelIngest()">
      Cancel
    </button>
  </div>
</div>
```

- [ ] **Step 4: Update form submit handler**

Change the event listener to first do preview:

```javascript
document.getElementById('ingest-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  // Phase 1: Extract keywords
  const btn = document.getElementById('ingest-btn');
  btn.disabled = true;
  btn.innerHTML = 'Extracting...';

  const formData = new FormData(e.target);

  try {
    const res = await fetch('/ingest/preview', { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.text();
      document.getElementById('progress-box').innerHTML = `<p class="err">Preview failed: ${err}</p>`;
      btn.disabled = false;
      btn.innerHTML = 'Ingest';
      return;
    }
    const data = await res.json();
    showKeywordPreview(data);
  } catch(err) {
    document.getElementById('progress-box').innerHTML = `<p class="err">Error: ${err.message}</p>`;
    btn.disabled = false;
    btn.innerHTML = 'Ingest';
  }
});
```

- [ ] **Step 5: Add keyword preview rendering**

```javascript
let _previewData = null;

function showKeywordPreview(data) {
  _previewData = data;
  const container = document.getElementById('keyword-preview');
  const chips = document.getElementById('keyword-chips');
  chips.innerHTML = '';
  container.style.display = 'block';

  const allKeywords = [
    ...data.keywords.existing.map(k => ({ kw: k, existing: true })),
    ...data.keywords.new.map(k => ({ kw: k, existing: false })),
  ];

  allKeywords.forEach(({ kw, existing }) => {
    const chip = document.createElement('span');
    chip.className = 'kw-chip';
    if (existing) chip.style.borderColor = 'var(--accent-dim)';
    else chip.style.borderColor = 'var(--info-dim)';

    if (!existing) {
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = true;
      checkbox.dataset.keyword = kw;
      checkbox.style.marginRight = '0.25rem';
      checkbox.style.accentColor = 'var(--info)';
      chip.appendChild(checkbox);
    }

    const txt = document.createTextNode(kw);
    chip.appendChild(txt);

    if (existing) {
      const check = document.createElement('span');
      check.textContent = ' ✓';
      check.style.color = 'var(--accent)';
      check.style.fontSize = '0.65rem';
      chip.appendChild(check);
    }

    chips.appendChild(chip);
  });

  document.getElementById('ingest-btn').style.display = 'none';
  document.getElementById('keyword-preview').scrollIntoView({ behavior: 'smooth' });
}

async function confirmIngest() {
  const previewId = _previewData.preview_id;
  const checkboxes = document.querySelectorAll('#keyword-chips input[type="checkbox"]:checked');
  const acceptedKeywords = Array.from(checkboxes).map(cb => cb.dataset.keyword);

  // Build request
  const payload = { preview_id: previewId, accepted_keywords: acceptedKeywords };

  // Start SSE stream
  document.getElementById('keyword-preview').style.display = 'none';
  document.getElementById('progress-card').classList.add('active');
  document.getElementById('progress-box').innerHTML = '<p>Starting pipeline...</p>';

  try {
    const res = await fetch('/ingest/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.job_id) throw new Error('No job_id');
    startSSEStream(data.job_id);
  } catch(err) {
    document.getElementById('progress-box').innerHTML = `<p class="err">Error: ${err.message}</p>`;
    resetIngestUI();
  }
}

function cancelIngest() {
  _previewData = null;
  document.getElementById('keyword-preview').style.display = 'none';
  resetIngestUI();
}

function resetIngestUI() {
  const btn = document.getElementById('ingest-btn');
  btn.disabled = false;
  btn.style.display = '';
  btn.innerHTML = '<svg>...</svg> Ingest';
}
```

- [ ] **Step 6: Refactor SSE stream handling**

Extract SSE start into a reusable function since both old ingest and new /ingest/run need it:

```javascript
let activeSource = null;

function startSSEStream(jobId) {
  const box = document.getElementById('progress-box');
  if (activeSource) { activeSource.close(); activeSource = null; }

  activeSource = new EventSource('/stream/' + jobId);
  activeSource.onmessage = (evt) => {
    if (evt.data === '[FINAL]') {
      activeSource.close();
      activeSource = null;
      // Show saved note etc — same as current logic
      handleStreamComplete(box);
      return;
    }
    if (evt.data.includes('ping -')) return;
    let data = evt.data;
    if (data.includes('Warning:') || data.includes('warning:')) {
      data = data.replace(/<p>/, '<p class="warn">');
    } else if (data.includes('Error:') || data.includes('error:') || data.includes('Skipped:')) {
      data = data.replace(/<p>/, '<p class="err">');
    } else if (data.includes('Saved ->')) {
      data = data.replace(/<p>/, '<p class="success">');
    }
    box.innerHTML += data;
    box.scrollTop = box.scrollHeight;
  };
  activeSource.onerror = () => {
    activeSource.close();
    activeSource = null;
    resetIngestUI();
    box.innerHTML += '<p class="err">Connection lost</p>';
  };
}
```

- [ ] **Step 7: Commit**

```
git add templates/index.html
git commit -m "feat: two-phase ingest UI, discovery panel moved up with trigger button"
```

---

### Task 8: Migration script — tags to keywords

**Files:**
- Create: `scripts/migrate_tags_to_keywords.py`

- [ ] **Step 1: Write migration script**

```python
#!/usr/bin/env python3
"""One-time migration: rename tags frontmatter to keywords in all vault notes.

Also adds [[wikilink]] keywords section to notes that have keywords but no wikilink section.
"""
import re
from pathlib import Path
import frontmatter as fm

VAULT_PATH = Path("/Users/vladbrincoveanu/Library/Mobile Documents/iCloud~md~obsidian/Documents/PersonalWiki")


def migrate_note(filepath: Path) -> bool:
    """Migrate a single note. Returns True if changed."""
    raw = filepath.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return False

    parsed = fm.parse(raw)
    metadata, body = parsed

    if "tags" not in metadata and "keywords" in metadata:
        return False  # Already migrated

    if "tags" not in metadata:
        return False  # No tags to migrate

    # Rename tags to keywords
    keywords = metadata.pop("tags", [])
    metadata["keywords"] = keywords

    # Write updated frontmatter
    post = fm.Post(body, **metadata)
    filepath.write_text(fm.dumps(post), encoding="utf-8")

    # Add [[wikilink]] section if keywords exist and no ## Keywords section
    if keywords and "## Keywords" not in body:
        raw = filepath.read_text(encoding="utf-8")
        links = " · ".join(f"[[{kw}]]" for kw in keywords)
        # Find first ## heading
        lines = raw.split("\n")
        insert_at = None
        for i, line in enumerate(lines):
            if line.startswith("## "):
                insert_at = i + 1
                break
        if insert_at is not None:
            lines.insert(insert_at, f"\n## Keywords\n{links}")
            filepath.write_text("\n".join(lines), encoding="utf-8")

    return True


def main():
    migrated = 0
    for md_file in sorted(VAULT_PATH.rglob("*.md")):
        try:
            if migrate_note(md_file):
                print(f"Migrated: {md_file.relative_to(VAULT_PATH)}")
                migrated += 1
        except Exception as e:
            print(f"Error migrating {md_file}: {e}")

    print(f"\nDone. Migrated {migrated} notes.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test the script on a copy of the vault first**

Run: `python -m pytest tests/ -v` (ensure all tests pass before running migration)

- [ ] **Step 3: Run the migration**

Run: `python scripts/migrate_tags_to_keywords.py`

- [ ] **Step 4: Verify a migrated note**

Read one migrated file to check frontmatter and wikilinks.

- [ ] **Step 5: Commit**

```
git add scripts/migrate_tags_to_keywords.py
git commit -m "feat: add tags-to-keywords migration script"
```
