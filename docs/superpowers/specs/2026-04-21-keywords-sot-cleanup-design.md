# Keywords SOT Cleanup — Design Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Simplify the keywords system to be a single user-managed list. Discovery reads keywords as read-only and never creates new ones. Deleting a keyword cascades to delete all discovery-found articles.

**Architecture:** Remove all amplification/graph-extraction machinery. Keywords come only from user input via UI. Discovery only reads `_keywords`.

---

## Current State (Problems)

- `_keywords` — manual keywords (5 entries, some garbage: URL as keyword)
- `_keywords-suppressed` — 40 entries of old amplified keywords (legacy blocklist)
- `_graph_keywords` — cached graph-extracted keywords from amplification era
- `core/graph_interests.py` — 300+ lines of hub/leaf extraction with LLM validation
- `suppress_keyword()` — writes to `_keywords-suppressed`
- `remove_keyword()` — doesn't cascade delete source_keyword articles
- Discovery amplifies: `_scheduler_loop` adds explore keywords to `_keywords` every 5th cycle

---

## Design

### Single Source of Truth

`_keywords` file is the **only** keyword store. Format: one keyword per line.

```
machine-learning
quantum-physics
startup-valuation
```

**No `_keywords-suppressed`**. **No `_graph_keywords`**.

### Keyword Operations

| Operation | Behavior |
|-----------|----------|
| Add keyword | User types in UI → `keywords_manager.add_keyword()` → appends to `_keywords` |
| Remove keyword | User clicks X in UI → `keywords_manager.remove_keyword()` → deletes from `_keywords` → cascades |
| List keywords | Read `_keywords` → return to UI |

### Cascade Delete on Keyword Removal

When `remove_keyword("machine-learning")` is called:
1. Remove `"machine-learning"` from `_keywords`
2. Scan vault notes for files where `source_keyword: machine-learning` in frontmatter
3. Delete those files from vault
4. Delete those files from LanceDB vector store
5. Remove `[[wikilink]]` references to keyword from remaining vault files (existing behavior)
6. Delete orphan stubs where filename matches keyword (existing behavior)

### Discovery: Read-Only Keywords

Discovery scheduler reads `_keywords` but **never writes to it**.
- `DiscoveryScheduler._keywords` is populated from `_keywords` file only
- Amplification loop disabled (stubs return)
- `extract_interests()` never called
- `_keywords-suppressed` never written to

### UI Shows Single Keyword List

- No separate "manual" vs "graph" buckets
- Single list of all keywords
- Each has X button to delete
- No add button in UI (user types new keywords)

---

## Modules

### Module: `vault/keywords_manager.py`
- **Responsibility:** Read/write `_keywords` file, manage cascade deletes
- **Interface:** `add_keyword(kw)`, `remove_keyword(kw)`, `load_keywords()`, `list_keywords()`
- **Dependencies:** `vault.doctor` for cascade delete
- **Size target:** ~100 lines

### Module: `core/discovery_scheduler.py`
- **Responsibility:** Periodic discovery using keywords as read-only input
- **Interface:** Reads `_keywords` only; never writes to it
- **Changes:** Amplification stubs return empty; `extract_interests()` not called
- **Size target:** ~800 lines (no size change needed)

### Module: `core/graph_interests.py`
- **Responsibility:** (DEPRECATED) No longer used for keyword extraction
- **Interface:** N/A
- **Action:** Delete file

### Module: `vault/doctor.py`
- **Responsibility:** Vault cleanup, cascade delete by source_keyword
- **Interface:** `run_vault_doctor(active_keywords)`, `purge_keyword(keyword)` already exists
- **Changes:** `purge_keyword()` already handles cascade; ensure it handles `source_keyword` matching
- **Size target:** ~150 lines

### Module: `templates/index.html`
- **Responsibility:** UI for keyword management (single list, delete button)
- **Changes:** Remove "manual" vs "graph" separation; single keyword list
- **Size target:** ~30 lines changed

---

## Files to DELETE

- `core/graph_interests.py` — amplification machinery, no longer needed
- `~/.personalWiki/_graph_keywords` — cached graph keywords (cleanup)
- `vault/_keywords-suppressed` — legacy suppression list (cleanup)

## Files to MODIFY

- `core/discovery_scheduler.py` — disable amplification, read-only keywords
- `core/keywords_manager.py` — simplify, remove suppress functions
- `vault/doctor.py` — ensure `purge_keyword()` handles `source_keyword` cascade
- `templates/index.html` — single keyword list UI

## Files to CREATE

- Migration script to clean up `_keywords` (remove URL, dedupe)

---

## Notes

- `source_keyword` frontmatter field: already implemented in `vault/writer.py` and `pipeline.py`
- Cascade delete via `source_keyword` frontmatter: **NOT YET IMPLEMENTED** — needs to be added to `purge_keyword()` or a new function
- `purge_keyword()` currently only handles wikilinks + orphan stubs — source_keyword cascade is new behavior
