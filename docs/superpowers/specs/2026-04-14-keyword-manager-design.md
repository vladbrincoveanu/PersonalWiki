# Keyword Manager — Design

**Date:** 2026-04-14
**Goal:** Add a UI panel in the FastAPI web app for viewing, adding, and removing interest keywords. Manual keywords persist in `vault/.interests`. Removing a keyword triggers automatic purge of all vault files containing it.

## Context

The `extract_interests()` function in `core/graph_interests.py` extracts keywords from two sources:
1. **Vault graph** — wikilinks and frontmatter tags in `.md` files
2. **Manual keywords** — stored in `vault/.interests` (one per line)

The scheduler refreshes its keyword list from `extract_interests()` periodically. The current UI (`app.py` + `templates/index.html`) only supports URL/PDF ingestion, not keyword management.

## Storage

**File:** `vault/.interests`
- Plain text, one keyword per line
- Created automatically on first `add` operation if it doesn't exist
- Blank lines and lines starting with `#` are ignored
- Keywords are case-sensitive and stored as-is

**Path:** resolved relative to `VAULT_PATH` from `config.py`

## API Endpoints

### `GET /keywords`

Returns all active keywords with breakdown by source.

**Response:** `200 OK`
```json
{
  "keywords": ["Claude", "Anthropic", "actiuni", "BVB", ...],
  "manual": ["actiuni", "BVB"],
  "graph": ["Claude", "Anthropic", ...],
  "total": 71
}
```

### `POST /keywords/add`

Adds a keyword to `vault/.interests`. Keyword is immediately included in the next discovery cycle.

**Request body:** `{"keyword": "actiuni"}`

**Response:** `200 OK`
```json
{"added": "actiuni", "manual_count": 6}
```

**Errors:**
- `400` — empty or whitespace-only keyword
- `409` — keyword already in `.interests`

### `POST /keywords/remove`

Removes a keyword from `vault/.interests` and immediately purges all vault files containing it (as wikilink `[[keyword]]` or anywhere in file text). Returns list of purged files.

**Request body:** `{"keyword": "no-transcript"}`

**Response:** `200 OK`
```json
{
  "removed": "no-transcript",
  "purged": ["vault/notes/no-transcript-yt.md", "vault/notes/missing-article.md"],
  "purged_count": 2
}
```

**Behavior:**
- Searches recursively in `vault/` for all `.md` files
- Matches if `[[keyword]]` OR raw text contains the keyword (case-sensitive)
- Files are permanently deleted (no trash/recycle bin)
- Always removes keyword from `.interests` even if no files matched

## DiscoveryScheduler Integration

Modify `core/discovery_scheduler.py`:

1. `_refresh_keywords()` — after calling `extract_interests()`, merge in manual keywords from `vault/.interests`
2. Add `_load_manual_keywords()` method that reads and parses `.interests`
3. Add `_save_manual_keywords()` method
4. Scheduler exposes `add_keyword(kw)` and `remove_keyword(kw)` that call the above

The `DiscoveryScheduler` instance created in `app.py` lifespan is the single source of truth for the running keyword list.

## UI — `templates/index.html`

Add a collapsible **"Keywords"** section below the ingest form:

**Layout:**
```
▼ Keywords (71)
  [Claude] [Anthropic] [BVB] [actiuni] [+ Add]
  no-transcript ✕  |  missing-article ✕  |  ...
```

- Chips for all keywords (scrollable)
- `✕` button on each chip → POST /keywords/remove (auto-purge)
- `[+ Add]` input → POST /keywords/add on Enter or button click
- `[+ Add]` expands inline to a text input with add button
- Collapsed state shows only count: `▶ Keywords (71)`

**Implementation:** Use HTMX for all interactions (no full page reloads). Dark-themed chips matching the existing card style.

## Files to Create/Modify

```
core/discovery_scheduler.py   [MODIFIED] add _load_manual_keywords, _save_manual_keywords,
                               add_keyword, remove_keyword; modify _refresh_keywords
app.py                        [MODIFIED] add GET /keywords, POST /keywords/add, POST /keywords/remove
templates/index.html           [MODIFIED] add Keywords panel section
tests/test_discovery_scheduler.py [MODIFIED] add tests for manual keyword add/remove
```

## Error Handling

- `.interests` missing → treat as empty list, create on first add
- File read/write errors → return `500` with error message
- Purge errors (e.g., file locked) → log warning, continue deleting remaining files, report partial purge
- Keyword not found in `.interests` on remove → return `404`

## Safety Considerations

- Purge is case-sensitive and matches anywhere in file content — not just wikilinks
- Files are permanently deleted, not moved to trash
- No undo mechanism
- User should understand this before using — no gatekeeping (Option A from clarification)

## Testing

1. `test_add_keyword_persists_to_file` — add keyword, verify `.interests` contains it
2. `test_add_duplicate_returns_409` — add same keyword twice, verify `409`
3. `test_remove_keyword_purges_files` — create temp vault with files containing keyword, remove keyword, verify files deleted
4. `test_remove_keyword_not_in_vault` — remove keyword that exists in `.interests` but no files contain it, verify returns empty `purged` list
5. `test_get_keywords_returns_all_sources` — verify response includes both manual and graph keywords
