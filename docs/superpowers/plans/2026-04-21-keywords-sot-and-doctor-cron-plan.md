# Keywords SOT + Doctor Cron Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `source_keyword` through the pipeline, disable amplification, then add a daily doctor cron that cleans untitled/sparse/orphaned notes.

**Architecture:** Three independent parts: (1) `source_keyword` wiring — two-line param adds through `pipeline.py` and `writer.py`; (2) doctor module — rename `junk_cleaner.py` to `doctor.py` and expand `cleanup_junk()` into `run_vault_doctor()` with all five junk criteria; (3) doctor scheduler — a new `DoctorScheduler` class in `core/doctor_scheduler.py` with a 24h timer thread, started in `app.py` lifespan.

**Tech Stack:** Python stdlib (`threading`, `time`), FastAPI lifespan, frontmatter, LanceDB vector store.

---

## Before You Start

Check current state of the two key files you will modify first:

```bash
# Verify source_keyword is NOT yet in pipeline.py
grep -n "source_keyword" /Users/vladbrincoveanu/Desktop/Startup/personalWiki/pipeline.py

# Verify current write_note call in pipeline.py
grep -n "write_note" /Users/vladbrincoveanu/Desktop/Startup/personalWiki/pipeline.py
```

Expected: both return no matches (the wiring doesn't exist yet).

---

## File Map

| File | Role |
|------|------|
| `pipeline.py` | Add `source_keyword` param, pass to `write_note()` |
| `vault/writer.py` | Accept and write `source_keyword` to frontmatter metadata |
| `core/discovery_scheduler.py` | Pass `source_keyword` in `_run_pipeline()`; make `_amplify_from_note()` a no-op |
| `vault/junk_cleaner.py` | Rename to `vault/doctor.py`, rewrite `cleanup_junk()` → `run_vault_doctor()` |
| `core/doctor_scheduler.py` | **New** — `DoctorScheduler` class |
| `app.py` | Start `DoctorScheduler` in `lifespan()` |

---

## Task 1: Add `source_keyword` to `write_note()` frontmatter

**Files:**
- Modify: `vault/writer.py:273-326`

- [ ] **Step 1: Read current `write_note()` signature**

Run: `grep -n "def write_note\|is_discovery" /Users/vladbrincoveanu/Desktop/Startup/personalWiki/vault/writer.py`

- [ ] **Step 2: Add `source_keyword: str | None = None` to `write_note()` signature**

In `vault/writer.py` line 279, change:
```python
def write_note(
    note: dict,
    source: str,
    ingested_date: str | None = None,
    images: Sequence[bytes] = (),
    entity_statuses: list[dict] = (),
    is_discovery: bool = False,
) -> str:
```
to:
```python
def write_note(
    note: dict,
    source: str,
    ingested_date: str | None = None,
    images: Sequence[bytes] = (),
    entity_statuses: list[dict] = (),
    is_discovery: bool = False,
    source_keyword: str | None = None,
) -> str:
```

- [ ] **Step 3: Add `source_keyword` to metadata dict (after `discovery: auto` block)**

In `vault/writer.py` around line 307-308, after:
```python
    if is_discovery:
        metadata["discovery"] = "auto"
```
add:
```python
    if source_keyword:
        metadata["source_keyword"] = source_keyword
```

- [ ] **Step 4: Verify the change**

Run: `grep -n "source_keyword" /Users/vladbrincoveanu/Desktop/Startup/personalWiki/vault/writer.py`
Expected: three matches — parameter, `if source_keyword:`, and `metadata["source_keyword"]`

---

## Task 2: Add `source_keyword` to `run_pipeline()` and pass it through

**Files:**
- Modify: `pipeline.py:87-210`

- [ ] **Step 1: Read `run_pipeline()` signature and `write_note()` call**

Run: `sed -n '87,95p' /Users/vladbrincoveanu/Desktop/Startup/personalWiki/pipeline.py` and `sed -n '207,210p' /Users/vladbrincoveanu/Desktop/Startup/personalWiki/pipeline.py`

- [ ] **Step 2: Add `source_keyword: str | None = None` to `run_pipeline()` signature**

In `pipeline.py` line 93 (after `is_discovery: bool = False`), add:
```python
    source_keyword: str | None = None,
```

- [ ] **Step 3: Pass `source_keyword` to `write_note()`**

In `pipeline.py` around line 207-210, change:
```python
    path = write_note(
        note, source=source, images=images, entity_statuses=entity_statuses,
        is_discovery=is_discovery,
    )
```
to:
```python
    path = write_note(
        note, source=source, images=images, entity_statuses=entity_statuses,
        is_discovery=is_discovery,
        source_keyword=source_keyword,
    )
```

- [ ] **Step 4: Verify**

Run: `grep -n "source_keyword" /Users/vladbrincoveanu/Desktop/Startup/personalWiki/pipeline.py`
Expected: two matches — parameter and the `write_note` call.

---

## Task 3: Wire `source_keyword` in `_run_pipeline()` and disable amplification

**Files:**
- Modify: `core/discovery_scheduler.py`

- [ ] **Step 1: Find `_run_pipeline()` method**

Run: `grep -n "_run_pipeline\|run_pipeline" /Users/vladbrincoveanu/Desktop/Startup/personalWiki/core/discovery_scheduler.py | head -20`

- [ ] **Step 2: Add `source_keyword=keyword` to the `run_pipeline()` call in `_run_pipeline()`**

The `_run_pipeline()` method is a local helper inside `DiscoveryScheduler` (not to be confused with the module-level `run_pipeline` function in `pipeline.py`). Find the line inside `_run_pipeline()` that calls `run_pipeline(url=url, is_discovery=True)` and change it to:
```python
            await run_pipeline(url=url, is_discovery=True, source_keyword=keyword)
```

- [ ] **Step 3: Find and disable `_amplify_from_note()`**

Run: `grep -n "_amplify_from_note\|async def _amplify" /Users/vladbrincoveanu/Desktop/Startup/personalWiki/core/discovery_scheduler.py`

- [ ] **Step 4: Make `_amplify_from_note()` a no-op**

Find `async def _amplify_from_note(self, note: dict):` and replace the entire body (everything after the docstring) with:
```python
        # Amplification disabled — keywords are user-owned only
        return
```

Keep the docstring. The `note` parameter is still accepted for API compatibility.

- [ ] **Step 5: Verify**

Run: `grep -n "Amplification:" /Users/vladbrincoveanu/Desktop/Startup/personalWiki/core/discovery_scheduler.py`
Expected: only comments or disabled code references.

---

## Task 4: Rewrite `vault/junk_cleaner.py` → `vault/doctor.py`

**Files:**
- Create: `vault/doctor.py` (replaces `vault/junk_cleaner.py`)
- Delete: `vault/junk_cleaner.py` after verifying new file works

- [ ] **Step 1: Read current `junk_cleaner.py` to understand its structure**

```bash
cat /Users/vladbrincoveanu/Desktop/Startup/personalWiki/vault/junk_cleaner.py
```

- [ ] **Step 2: Create `vault/doctor.py` with `run_vault_doctor()`**

Write the complete new file:

```python
"""
Vault doctor — aggressive cleanup of junk notes.

A note is "junk" if ANY of:
1. Untitled/garbage: No H1, or title is "Untitled"/same as slug, or [NO_TRANSCRIPT]/[TRANSLATION_FAILED]
2. Sparse: raw_text < 200 chars
3. Orphaned discovery: discovery: auto but no wikilink to any active keyword
4. Video no-content: type: video AND raw_text < 50 chars
5. No body at all after frontmatter stripping
"""
import re
import logging
from pathlib import Path
import frontmatter
from config import NOTES_DIR

_logger = logging.getLogger(__name__)

def _slugify(text: str) -> str:
    """Slugify a title to match filename generation."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _is_junk_note(note: dict, active_keywords: list[str], file_stem: str) -> tuple[bool, str]:
    """
    Return (is_junk, reason) for a note.
    """
    title = note.get("title", "")
    raw_text = note.get("raw_text", "")
    content_type = note.get("type", "article")
    is_discovery = note.get("discovery") == "auto"
    source_keyword = note.get("source_keyword")

    # 4. Video no-content (existing rule)
    if content_type == "video" and len(raw_text) < 50:
        return True, "video-no-content"

    # 1. Untitled/garbage
    body = note.get("_body", "")
    first_line = body.split("\n", 1)[0].strip() if body else ""
    has_h1 = first_line.startswith("# ")
    h1_title = first_line[2:].strip() if has_h1 else ""
    slug_from_title = _slugify(title)

    if not has_h1:
        return True, "untitled-no-h1"
    if title.lower() == "untitled":
        return True, "untitled-exact"
    if h1_title.lower() == "untitled":
        return True, "untitled-h1"
    if file_stem == slug_from_title and title.lower() == "untitled":
        return True, "untitled-slug-match"
    if "[NO_TRANSCRIPT]" in title or "[TRANSLATION_FAILED]" in title:
        return True, "transcript-failed"

    # 5. No body at all
    stripped_body = body.strip()
    if not stripped_body:
        return True, "no-body"

    # 2. Sparse
    if len(raw_text) < 200:
        return True, "sparse"

    # 3. Orphaned discovery — discovery: auto but source_keyword not in active list
    if is_discovery:
        if source_keyword and source_keyword not in active_keywords:
            return True, "orphaned-discovery"
        # Also check if it has any wikilink to an active keyword
        wikilink_pattern = re.compile(r"\[\[([^\]|]+)\]\]?", re.IGNORECASE)
        linked_keywords = wikilink_pattern.findall(body)
        has_active_keyword_link = any(
            kw in active_keywords for kw in linked_keywords
        )
        if not has_active_keyword_link:
            return True, "orphaned-discovery-no-keyword-link"

    return False, ""


def run_vault_doctor(active_keywords: list[str]) -> dict[str, list[str]]:
    """
    Run all vault cleanup checks.
    Returns {"untitled": [...], "sparse": [...], "orphaned": [...], "video-no-content": [...], "deleted": [...]}.
    """
    if not NOTES_DIR.exists():
        return {"untitled": [], "sparse": [], "orphaned": [], "video-no-content": [], "deleted": []}

    from core.vector_store import get_store
    store = get_store()

    deleted: list[str] = []
    by_reason: dict[str, list[str]] = {
        "untitled": [], "sparse": [], "orphaned": [], "video-no-content": [], "deleted": []
    }

    for md_path in NOTES_DIR.rglob("*.md"):
        try:
            raw = md_path.read_text(encoding="utf-8")
            post = frontmatter.parse(raw)
            note = dict(post)
            note["_body"] = post.content

            is_junk, reason = _is_junk_note(note, active_keywords, md_path.stem)
            if not is_junk:
                continue

            by_reason[reason].append(str(md_path))
            by_reason["deleted"].append(str(md_path))
            _logger.info("Doctor: removing %s (%s): %s", md_path.name, reason, note.get("title", "?"))
            md_path.unlink()
            store.delete(str(md_path))
            deleted.append(str(md_path))
        except Exception as e:
            _logger.warning("Doctor: failed to process %s: %s", md_path.name, e)

    return by_reason


def cleanup_junk() -> list[str]:
    """
    Legacy wrapper — runs doctor with no active keywords (skips orphaned-discovery check).
    Kept for backward compatibility with existing imports.
    """
    return run_vault_doctor([])["deleted"]
```

- [ ] **Step 3: Verify new file**

Run: `/Users/vladbrincoveanu/Desktop/Startup/personalWiki/.venv/bin/python -c "from vault.doctor import run_vault_doctor, cleanup_junk; print('doctor.py loads OK')"`

- [ ] **Step 4: Replace old junk_cleaner.py**

Run: `mv /Users/vladbrincoveanu/Desktop/Startup/personalWiki/vault/junk_cleaner.py /Users/vladbrincoveanu/Desktop/Startup/personalWiki/vault/junk_cleaner.py.bak`

- [ ] **Step 5: Create symlink for backward compat (optional — or update imports)**

The `cleanup_junk()` wrapper in `doctor.py` handles backward compat for any code importing `cleanup_junk` from `vault.junk_cleaner`. But `discovery_scheduler.py` imports `cleanup_junk` from `vault.junk_cleaner`. Update that import:

In `core/discovery_scheduler.py` line 34, change:
```python
from vault.junk_cleaner import cleanup_junk
```
to:
```python
from vault.doctor import cleanup_junk
```

- [ ] **Step 6: Run existing tests**

Run: `/Users/vladbrincoveanu/Desktop/Startup/personalWiki/.venv/bin/python -m pytest /Users/vladbrincoveanu/Desktop/Startup/personalWiki/tests/ -v --tb=short 2>&1 | tail -30`
Expected: existing tests pass (may have pre-existing failures on main).

---

## Task 5: Create `core/doctor_scheduler.py`

**Files:**
- Create: `core/doctor_scheduler.py`

- [ ] **Step 1: Write `DoctorScheduler` class**

```python
"""
Daily doctor scheduler — runs vault cleanup on a timer.
"""
import logging
import threading
import time

_logger = logging.getLogger(__name__)


class DoctorScheduler:
    def __init__(self, interval_hours: int = 24):
        self._interval_seconds = interval_hours * 3600
        self._running = False
        self._task: threading.Thread | None = None

    def start(self, discovery_scheduler_ref) -> None:
        """
        Start the doctor loop. discovery_scheduler_ref is the DiscoveryScheduler instance.
        Keywords are read from discovery_scheduler_ref._keywords (the SOT).
        """
        self._running = True
        self._task = threading.Thread(
            target=self._loop,
            args=(discovery_scheduler_ref,),
            daemon=True,
            name="doctor-scheduler",
        )
        self._task.start()
        _logger.info("Doctor scheduler started (interval=%dh)", self._interval_seconds // 3600)

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.join(timeout=5)
        _logger.info("Doctor scheduler stopped")

    def _loop(self, discovery_scheduler_ref) -> None:
        from vault.doctor import run_vault_doctor
        while self._running:
            time.sleep(self._interval_seconds)
            if not self._running:
                break
            try:
                # Read active keywords from the DiscoveryScheduler SOT
                keywords = list(discovery_scheduler_ref._keywords)
                result = run_vault_doctor(keywords)
                _logger.info(
                    "Doctor: cleaned vault — untitled=%d sparse=%d orphaned=%d video-no-content=%d total_deleted=%d",
                    len(result["untitled"]),
                    len(result["sparse"]),
                    len(result["orphaned"]),
                    len(result["video-no-content"]),
                    len(result["deleted"]),
                )
            except Exception as e:
                _logger.error("Doctor: vault cleanup failed: %s", e)
```

- [ ] **Step 2: Verify it loads**

Run: `/Users/vladbrincoveanu/Desktop/Startup/personalWiki/.venv/bin/python -c "from core.doctor_scheduler import DoctorScheduler; print('doctor_scheduler.py loads OK')"`

---

## Task 6: Wire DoctorScheduler into app.py lifespan

**Files:**
- Modify: `app.py:31-39`

- [ ] **Step 1: Read current lifespan**

Run: `sed -n '31,41p' /Users/vladbrincoveanu/Desktop/Startup/personalWiki/app.py`

- [ ] **Step 2: Add doctor_scheduler import and global**

After line 18 (`_scheduler: DiscoveryScheduler | None = None`), add:
```python
_doctor_scheduler: DoctorScheduler | None = None
```

After line 15 (`from core.keywords_manager import load_manual_keywords`), add:
```python
from core.doctor_scheduler import DoctorScheduler
```

- [ ] **Step 3: Wire doctor start into `_get_scheduler()`**

The cleanest integration: start the doctor right after the scheduler is created and started, inside `_get_scheduler()` (which already runs before the first request).

After `await _scheduler.start(pipeline_func=run_pipeline)` in `_get_scheduler()`, add:
```python
        # Start daily doctor cron (only once, after scheduler is initialized)
        global _doctor_scheduler
        _doctor_scheduler = DoctorScheduler(interval_hours=24)
        _doctor_scheduler.start(_scheduler)
```

And in the `lifespan()` `finally` block, add:
```python
        if _doctor_scheduler:
            _doctor_scheduler.stop()
```

- [ ] **Step 4: Run to verify no import errors**

Run: `/Users/vladbrincoveanu/Desktop/Startup/personalWiki/.venv/bin/python -c "from app import app; print('app.py loads OK')"`

---

## Task 7: Run full test suite

- [ ] **Step 1: Run all tests**

Run: `/Users/vladbrincoveanu/Desktop/Startup/personalWiki/.venv/bin/python -m pytest /Users/vladbrincoveanu/Desktop/Startup/personalWiki/tests/ -v --tb=short 2>&1 | tail -40`

- [ ] **Step 2: Verify no regressions**

Compare test results to pre-change baseline (known pre-existing failures on main branch are OK).

---

## Task 8: Commit

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat: wire source_keyword through pipeline and add daily doctor cron

- Add source_keyword param to run_pipeline() and write_note()
- Disable amplification (keywords are user-owned only)
- Rename junk_cleaner.py -> doctor.py, expand cleanup criteria
- Add DoctorScheduler (24h timer) for daily vault cleanup
- Wire doctor into app.py lifespan

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Spec Coverage Check

| Spec Requirement | Task |
|-----------------|------|
| Wire `source_keyword` through pipeline | Task 1 + 2 + 3 |
| `source_keyword` in discovery note frontmatter | Task 1 |
| Disable amplification permanently | Task 3 |
| Rename junk_cleaner → doctor.py | Task 4 |
| Untitled/garbage detection | Task 4 (`_is_junk_note`) |
| Sparse <200 chars detection | Task 4 (`_is_junk_note`) |
| Orphaned discovery detection | Task 4 (`_is_junk_note`) |
| Video no-content <50 chars | Task 4 (`_is_junk_note`) |
| DoctorLogger cleanup for removed keywords | Task 4 (in `run_vault_doctor()`) |
| DoctorScheduler with 24h timer | Task 5 |
| Start doctor in app.py lifespan | Task 6 |
