# LanceDB Schema Migration Fix — PersonalWiki

**Date:** 2026-04-30
**Type:** Bug Fix + Defense-in-Depth

---

## Problem Statement

Existing `.vke_index/notes.lance` table was created on 2026-04-12 with 1024-dimensional vectors (LM Studio qwen3-embedding era). After the fastembed-lock fix merged (commit `149c1ef`), `embed()` now correctly returns 384d vectors. However:

1. `VectorStore.__init__()` opens the existing table without validating its schema
2. `store.search(vector)` queries the 1024d table with a 384d vector → LanceDB error: `query dim(384) doesn't match column vector dim(1024)`
3. `store.exists(url)` also hits the broken table, returns incorrect results
4. Pipeline re-ingests same URLs multiple times (duplicate entries in logs)

**Two bugs:**
- **Immediate:** Dimension mismatch crashes search/exists on every pipeline run
- **Cascading:** Duplicate ingestion because exists() returns wrong answer

---

## Architecture

### Decision 1: Data Loss — Drop + Recreate

Dropping the `notes` table loses all indexed data. The vault scanner (`vault/scanner.py`) can rebuild the entire index from `.md` files by re-embedding and re-upserting each note. This is acceptable because:
- The vector index is a cache, not source of truth
- Source of truth is the Obsidian vault (`.md` files)
- Rebuild is deterministic and complete

**Alternative considered:** LanceDB schema evolution (alter column type). Not supported by LanceDB cleanly — would require data copy anyway.

### Decision 2: When to Detect — `__init__()` not `upsert()`

Detect and fix the mismatch at `VectorStore.__init__()` time, before any method (`search`, `exists`, `upsert`) touches the table. This ensures:
- No query ever hits a broken table
- Migration happens once per process lifetime
- Fail-fast: problem is visible immediately on startup

**Alternative considered:** Catch at `upsert()` only. Rejected because `search()` and `exists()` would still crash or return wrong results.

### Decision 3: Future-Proof — Derive Dimension Dynamically

Derive the expected dimension from `embed("test")` at runtime rather than hardcoding `384`. This creates a single source of truth: the `embed()` function itself. If `EMBED_MODEL` changes in config, the schema adapts automatically.

**Alternative considered:** Hardcode dimension constant. Rejected — would create the same bug again if the embedding model ever changes.

---

## Module Design

### `core/vector_store.py` — `VectorStore.__init__()`

```python
def __init__(self, index_path: str | Path):
    self._db = lancedb.connect(str(index_path))
    if TABLE_NAME not in self._db.table_names():
        self._table = self._db.create_table(TABLE_NAME, schema=SCHEMA)
    else:
        self._table = self._db.open_table(TABLE_NAME)
        # Detect schema dimension mismatch and auto-migrate
        self._migrate_if_needed()

    if ENTITIES_TABLE not in self._db.table_names():
        self._entities_table = self._db.create_table(ENTITIES_TABLE, schema=ENTITIES_SCHEMA)
    else:
        self._entities_table = self._db.open_table(ENTITIES_TABLE)
```

### New method: `_migrate_if_needed()`

```python
def _migrate_if_needed(self):
    """Check vector schema dimension; migrate if mismatched."""
    from core.embeddings import embed
    actual_dim = _detect_table_dim(self._table)
    expected_dim = len(embed("test"))
    if actual_dim != expected_dim:
        logging.warning(
            f"Vector schema mismatch: table has {actual_dim}d, "
            f"embed() returns {expected_dim}d. Dropping and recreating table."
        )
        self._db.drop_table(TABLE_NAME)
        self._table = self._db.create_table(TABLE_NAME, schema=SCHEMA)
```

### Helper: `_detect_table_dim()`

Inspect the LanceDB table schema via PyArrow to read the vector field's dimension:

```python
def _detect_table_dim(table) -> int:
    schema = table.schema
    vector_field = schema.field("vector")
    return vector_field.type.list_field.type.byte_width // 4  # float32 = 4 bytes
```

---

## Migration Flow

```
VectorStore() initialized
  ├─ connect to .vke_index
  ├─ notes table exists? → YES → open_table()
  │     └─ _migrate_if_needed()
  │           ├─ probe schema → detect 1024d
  │           ├─ call embed("test") → 384d
  │           ├─ mismatch detected
  │           ├─ log warning
  │           └─ drop_table("notes") → recreate with SCHEMA (384d)
  └─ notes table exists? → NO → create_table(SCHEMA)
```

After migration: all vector operations use correct 384d schema.

---

## Data Loss Handling

If migration occurs:
1. All rows in `notes` table are deleted
2. `vault/scanner.py` rebuilds index: `scan_vault()` → re-embed all `.md` files → `store.upsert()`
3. User must run scanner after migration (document this in warning message)

**User-facing warning logged:**
```
WARNING: Vector schema mismatch detected (table=1024d, expected=384d).
Index has been cleared. Run `python -m vault.scanner` to rebuild.
```

---

## Files to Modify

| File | Change |
|------|--------|
| `core/vector_store.py` | Add `_migrate_if_needed()` and `_detect_table_dim()` to `VectorStore.__init__()` |

---

## Backward Compatibility

- If `actual_dim == expected_dim`: no-op, existing behavior unchanged
- If table doesn't exist: create with correct SCHEMA (existing behavior unchanged)
- `entities` table: no vector column, never needs migration

---

## Test Plan

### Unit Test

**`test_vector_store.py::test_migrate_on_dimension_mismatch`:**
1. Create temp LanceDB dir
2. Create a `notes` table with 1024d vectors (using raw PyArrow)
3. Create `VectorStore` pointing to that dir
4. Assert `_table` was dropped and recreated with 384d schema

```python
def test_migrate_on_dimension_mismatch(tmp_path):
    import pyarrow as pa
    # Create a table with wrong dimension
    bad_schema = pa.schema([
        pa.field("path", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 1024)),  # wrong!
        pa.field("links", pa.list_(pa.string())),
        pa.field("metadata", pa.string()),
    ])
    db = lancedb.connect(str(tmp_path))
    db.create_table("notes", schema=bad_schema)

    # VectorStore should detect and migrate
    from core.vector_store import VectorStore
    store = VectorStore(str(tmp_path))

    # Verify table now has correct schema
    actual_dim = _detect_table_dim(store._table)
    assert actual_dim == 384
```

### Smoke Test (Playwright)

See `tests/smoke/` — run full ingestion pipeline on a real URL and verify:
1. No "query dim mismatch" error in logs
2. No duplicate ingestion warnings
3. Note written to vault

---

## Success Criteria

1. `VectorStore` with 1024d table on disk auto-migrates to 384d on init
2. `embed("test")` returns 384 dimensions
3. `store.search(embed("test"))` returns results (no dimension error)
4. `store.exists(url)` returns correct answer (no dimension error)
5. No duplicate ingestion for same URL
6. Unit test passes
7. Smoke test passes (after index rebuild)

---

## Post-Fix Verification

```bash
# 1. Verify dimension
python3 -c "from core.embeddings import embed; print(len(embed('test')))"  # → 384

# 2. Verify schema detection
python3 -c "
from core.vector_store import VectorStore, _detect_table_dim
store = VectorStore('.vke_index')
print(_detect_table_dim(store._table))  # → 384
"

# 3. Verify search works (no dimension error)
python3 -c "
from core.vector_store import get_store
store = get_store()
result = store.search([0.0] * 384, top_k=1)
print('search OK')
"

# 4. Run scanner to rebuild index
python -m vault.scanner
```
