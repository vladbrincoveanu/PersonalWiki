# LanceDB Schema Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix vector dimension mismatch crash — `notes.lance` has 1024d vectors but `embed()` now returns 384d. Auto-migrate on init.

**Architecture:** Add `_migrate_if_needed()` in `VectorStore.__init__()` that detects dimension mismatch and drops/recreates both `notes` and `personal_entities` tables. Scanner rebuilds from source markdown files.

**Tech Stack:** Python, LanceDB, PyArrow, FastEmbed

---

## Problem

The `.vke_index/notes.lance` table was created on 2026-04-12 with 1024-dimensional vectors (when `qwen3-embedding-4b-dwq` was used). After the fastembed lock fix, `embed()` now returns 384-dimensional vectors (`BAAI/bge-small-en-v1.5`). Querying crashes with:

```
query dim(384) doesn't match the column vector vector dim(1024)
```

The same risk exists for `personal_entities.lance`.

---

## File Map

**Modify:**
- `core/vector_store.py` — add migration helpers, update `upsert()` dimension guard
- `tests/test_vector_store.py` — add regression test, replace hardcoded `384` vectors

---

## Task 1: Add `_detect_table_dim()` helper

**Files:**
- Modify: `core/vector_store.py` — add function before `VectorStore` class (around line 82)

- [ ] Add `_detect_table_dim()` function before the `VectorStore` class:

```python
def _detect_table_dim(table) -> int:
    """Read vector field dimension from an open LanceDB table schema."""
    schema = table.schema
    vector_field = schema.field("vector")
    return vector_field.type.list_size
```

**Verification:** `grep -n "_detect_table_dim" core/vector_store.py` shows the function

---

## Task 2: Add migration infrastructure and `_migrate_if_needed()`

**Files:**
- Modify: `core/vector_store.py:1` — add `import logging`
- Modify: `core/vector_store.py` — add `_logger = logging.getLogger(__name__)` after imports
- Modify: `core/vector_store.py` — add `_migrate_if_needed()` method inside `VectorStore`
- Modify: `core/vector_store.py` — call `self._migrate_if_needed()` at end of `__init__()`
- Modify: `core/vector_store.py` — reset `global _store = None` after dropping tables

- [ ] Add `import logging` after existing imports (line 1-4)
- [ ] Add `_logger = logging.getLogger(__name__)` after imports
- [ ] Add `_migrate_if_needed()` method after entities table init in `__init__()` (after line 94):

```python
    def _migrate_if_needed(self):
        from core.embeddings import embed
        expected_dim = len(embed("test"))
        for table_name, table, schema in [
            (TABLE_NAME, self._table, SCHEMA),
            (ENTITIES_TABLE, self._entities_table, ENTITIES_SCHEMA),
        ]:
            try:
                actual_dim = _detect_table_dim(table)
                if actual_dim != expected_dim:
                    _logger.warning(
                        f"Mismatch in '{table_name}': table={actual_dim}d, embed={expected_dim}d. "
                        f"Dropping and recreating table."
                    )
                    self._db.drop_table(table_name)
                    if table_name == TABLE_NAME:
                        self._table = self._db.create_table(table_name, schema=schema)
                    else:
                        self._entities_table = self._db.create_table(table_name, schema=schema)
                    global _store
                    _store = None
                    _logger.warning(f"Index cleared. Run `python -m vault.scanner` to rebuild.")
            except Exception:
                pass
```

- [ ] Call `self._migrate_if_needed()` at end of `__init__()` (after line 94)
- [ ] Verify: `python -c "from core.vector_store import VectorStore; print('OK')"`

---

## Task 3: Replace hardcoded `384` in `upsert()` with dynamic dimension

**Files:**
- Modify: `core/vector_store.py:98-99` — upsert dimension guard

- [ ] Replace hardcoded `384` in `upsert()` dimension guard:

Line 98-99:
```python
        if len(vector) != 384:
            raise ValueError(f"Vector dimension must be 384, got {len(vector)}")
```

Replace with:
```python
        from core.embeddings import embed
        expected_dim = len(embed("test"))
        if len(vector) != expected_dim:
            raise ValueError(f"Vector dimension must be {expected_dim}, got {len(vector)}")
```

**Verification:** `python -c "from core.vector_store import VectorStore; print('upsert guard OK')"`

---

## Task 4: Add regression test for dimension migration

**Files:**
- Modify: `tests/test_vector_store.py` — add test at end of file

- [ ] Add regression test `test_migrate_on_dimension_mismatch` at end of test file:

```python
def test_migrate_on_dimension_mismatch(mock_store):
    """Verify VectorStore auto-migrates a wrong-dimension table."""
    import lancedb
    import pyarrow as pa

    store, tmp_dir = mock_store

    # Manually create a table with WRONG dimension (1024d) to simulate stale index
    db = lancedb.connect(str(tmp_dir))
    wrong_schema = pa.schema([
        pa.field("path", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 1024)),  # wrong dimension
        pa.field("links", pa.list_(pa.string())),
        pa.field("metadata", pa.string()),
    ])
    db.drop_table("notes")
    db.create_table("notes", schema=wrong_schema)

    # Re-open the store — should detect mismatch and recreate table
    store2 = VectorStore(index_path=str(tmp_dir))

    # Verify table was recreated with correct dimension (384d)
    table = store2._table
    actual_dim = table.schema.field("vector").type.list_size
    assert actual_dim == 384, f"Expected 384d, got {actual_dim}"
```

**Verification:** `python -m pytest tests/test_vector_store.py::test_migrate_on_dimension_mismatch -v`

---

## Task 5: Add `_embed_dim()` helper and fix hardcoded vectors in tests

**Files:**
- Modify: `tests/test_vector_store.py`

- [ ] Add `_embed_dim()` helper after imports at top of file:

```python
def _embed_dim():
    from core.embeddings import embed
    return len(embed("test"))
```

- [ ] Replace all hardcoded vector dimensions in test file:
  - `[0.1] * 384` → `[0.1] * _embed_dim()`
  - `[0.2] * 384` → `[0.2] * _embed_dim()`
  - `[float(i) / 10] * 384` → `[float(i) / 10] * _embed_dim()`
  - `[0.0] * 384` → `[0.0] * _embed_dim()`

**Verification:** `python -m pytest tests/test_vector_store.py -v --tb=short 2>&1 | tail -20`

---

## Task 6: Verify end-to-end

- [ ] Run scanner to rebuild index:

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && python -m vault.scanner
```

Expected: Re-indexes notes without crash

- [ ] Run hybrid_search to confirm no crash:

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && python -c "
from core.vector_store import get_store
store = get_store()
results = store.hybrid_search('attention mechanism', top_k=3)
print(f'Got {len(results)} results')
for r in results:
    print(f'  {r[\"path\"]}: score={r[\"score\"]:.4f}')
"
```

Expected: Returns results without dimension mismatch error

- [ ] Run full test suite:

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && python -m pytest tests/test_vector_store.py -v
```

Expected: All tests pass