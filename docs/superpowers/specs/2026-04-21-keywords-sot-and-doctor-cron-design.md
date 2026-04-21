# Keywords as Single Source of Truth + Doctor Cron

**Date:** 2026-04-21
**Status:** Draft

---

## Goal

Two related changes:
1. Keywords from the UI are the **single source of truth** for all downstream consumers: discovery, wikilink cleanup, doctor cleanup, and gap detection all read from the same list
2. A **daily doctor cron** aggressively cleans the vault — untitled stubs, sparse notes, orphaned discovery notes, and notes not linked to any keyword

---

## Principle

**Keywords are user-owned.** The UI keyword list is always authoritative. The vault graph only feeds INTO this list on refresh — never the other way around. Amplification (auto-adding keywords from notes) is permanently disabled.

---

## Part 1: Keywords as Single Source of Truth

### Problem

Currently `DiscoveryScheduler._keywords` is an in-memory list populated from two sources (graph + manual) but:
- The `source_keyword` param was added to `write_note()` but **never wired through `pipeline.py`** — discovery notes don't record which keyword found them
- Amplification still adds keywords to `_keywords` in-memory even though it should be disabled
- `vault/writer.py` received `source_keyword` but `pipeline.py` doesn't accept or forward it

### Fix 1a: Wire `source_keyword` through pipeline

**Module: `pipeline.py` — `run_pipeline()`**
- Add `source_keyword: str | None = None` parameter
- Pass it through to `write_note()`

**Module: `core/discovery_scheduler.py` — `_run_pipeline()`**
- Already calls `run_pipeline(url=url, is_discovery=True)` — add `source_keyword=keyword`

### Fix 1b: Disable amplification permanently

**Module: `core/discovery_scheduler.py` — `_amplify_from_note()`**
- Make the method a no-op (return immediately)
- Keyword scores (`_keyword_scores`) are still maintained so re-enabling later is safe

### Fix 1c: Ensure SOT consistency

All consumers read keywords from the same place: `_keywords` on the scheduler instance (populated from `VAULT_PATH/.interests`).

- `purge_keyword()` already reads the keywords file directly
- `cleanup_doctor()` (new, see below) must accept the active keyword list as a parameter, not re-scan the file

---

## Part 2: Doctor Cron — Vault Cleanup

### Problem

The existing `cleanup_junk()` only handles video notes with no transcript. It misses: untitled stubs, notes with garbage/no content, sparse notes (raw_text < 200 chars), and notes with no wikilink to any active keyword.

### Detection Criteria

A note is "junk" if ANY of:

1. **Untitled/garbage**: No H1 heading in body, OR H1 title is "Untitled" or identical to filename slug, OR title contains `[NO_TRANSCRIPT]` or `[TRANSLATION_FAILED]`
2. **Sparse**: `raw_text` < 200 characters
3. **Orphaned discovery**: Note has `discovery: auto` in frontmatter BUT no `[[wikilink]]` references to any active keyword in the UI list
4. **Video no-content**: `type: video` AND `raw_text` < 50 chars (existing rule, keep it)
5. **No body at all**: Parsed frontmatter body is empty after stripping frontmatter

### Module: `vault/junk_cleaner.py` — rename to `vault/doctor.py`

Rename the file and function to `run_vault_doctor()` to reflect the broader scope.

```python
def run_vault_doctor(active_keywords: list[str]) -> dict[str, list[str]]:
    """
    Run all vault cleanup checks.
    Returns {"untitled": [...], "sparse": [...], "orphaned": [...], "deleted": [...]}.
    """
```

- **Responsibility:** Diagnose and delete all categories of junk notes from vault + vector store
- **Interface:** `run_vault_doctor(active_keywords: list[str]) -> dict[str, list[str]]`
- **Dependencies:** `NOTES_DIR`, `VectorStore`, `frontmatter`
- **Size target:** < 200 lines

### DiscoveryLogger integration

The doctor also scrubs the `discovery_logger` ring buffer. Two scenarios:

**Removed keywords:** For each keyword no longer in the active list, call `remove_by_source(f"keyword: {kw}")` to purge all discovery log events for that keyword.

**Orphaned discovery notes:** When a note has `discovery: auto` in frontmatter but its `source_keyword` is not in the active keyword list, delete the note AND call `remove_by_source(f"keyword: {source_keyword}")` to clean up stale events.

```python
# In run_vault_doctor() — after collecting deleted note paths
from core.discovery_logger import get_discovery_logger
dl = get_discovery_logger()
removed_keywords = set(previous_active_keywords) - set(active_keywords)
for kw in removed_keywords:
    dl.remove_by_source(f"keyword: {kw}")
# Also clean up events for orphaned discovery notes being deleted
for note_path in orphaned_discovery_notes:
    note = frontmatter.parse(Path(note_path).read_text())
    source_kw = dict(note).get("source_keyword")
    if source_kw and source_kw not in active_keywords:
        dl.remove_by_source(f"keyword: {source_kw}")
```

---

## Part 3: Daily Cron Scheduling

### Where to run

The cron runs inside the FastAPI app lifespan, using a background timer thread (same pattern as `DiscoveryScheduler`). No external cron tools needed.

**Module: `core/doctor_scheduler.py`**

```python
class DoctorScheduler:
    def __init__(self, interval_hours: int = 24):
        self._interval = interval_hours * 3600
        self._running = False
        self._task: threading.Thread | None = None

    def start(self, scheduler_ref):
        """Start the doctor loop. scheduler_ref is the DiscoveryScheduler instance."""
        self._running = True
        self._task = threading.Thread(target=self._loop, args=(scheduler_ref,), daemon=True)
        self._task.start()

    def _loop(self, scheduler_ref):
        while self._running:
            time.sleep(self._interval)
            if not self._running:
                break
            keywords = scheduler_ref._keywords  # Read from SOT
            deleted = run_vault_doctor(keywords)
            _logger.info("Doctor: cleaned vault — %s", deleted)
```

- **Responsibility:** Run vault doctor on a daily timer, reading keywords from the DiscoveryScheduler SOT
- **Interface:** `DoctorScheduler.start(discovery_scheduler_instance)`
- **Dependencies:** `time`, `threading`, `run_vault_doctor`
- **Size target:** < 60 lines

### Integration

In `app.py` `lifespan()`, after `scheduler.start()`:

```python
doctor = DoctorScheduler(interval_hours=24)
doctor.start(scheduler)
```

Or if `INTEREST_REFRESH_INTERVAL` is already ~24h, just call `run_vault_doctor()` at the END of `_run_discovery_cycle()` — but a separate timer is safer so it runs even if discovery is disabled.

---

## Files to Change

| File | Change |
|------|--------|
| `pipeline.py` | Add `source_keyword` param, pass to `write_note()` |
| `core/discovery_scheduler.py` | Pass `source_keyword` in `_run_pipeline()`; make `_amplify_from_note()` a no-op |
| `vault/junk_cleaner.py` | Rename → `vault/doctor.py`; rename `cleanup_junk()` → `run_vault_doctor()` with full criteria |
| `core/doctor_scheduler.py` | **New file** — `DoctorScheduler` daily timer class |
| `app.py` | Start `DoctorScheduler` in `lifespan()` |

---

## Testing

1. `python -m pytest tests/test_keywords_manager.py -v` — all pass
2. Ingest a discovery URL → note frontmatter contains `source_keyword`
3. Trigger doctor manually → junk notes deleted from vault + vector store
4. Discovery logger events cleaned when their source keyword is removed from UI
5. Amplification never adds new keywords (verify `_keywords` list unchanged after discovery cycle)
