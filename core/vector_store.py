from contextlib import contextmanager
import re
from pathlib import Path
import lancedb
import logging
import pyarrow as pa

from observability import (
    observed_span,
    record_vector_operation,
    record_vector_search,
    record_vector_upsert,
)

_logger = logging.getLogger(__name__)

_SEARCH_TOKEN_RE = re.compile(r"[^\W]+(?:[-'_/+.#:][^\W]+)*[-+'#]*")


def _search_tokens(text: str) -> set[str]:
    """Tokenize entity text consistently for coarse and exact matching."""
    return set(_SEARCH_TOKEN_RE.findall(text.casefold()))


def _escape_like(value: str) -> str:
    """Escape a literal SQL LIKE value for LanceDB's string-only filter API."""
    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("'", "''")
    )

# The configured BGE-small model and LanceDB schema both use 384 dimensions.
# Keep startup and unit tests independent from a network model download; a model
# change must update this contract and trigger the migration path explicitly.
EMBEDDING_DIMENSION = 384

SCHEMA = pa.schema([
    pa.field("path", pa.string()),
    pa.field("content", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIMENSION)),
    pa.field("metadata", pa.string()),
    pa.field("timestamp", pa.int64()),
])

ENTITIES_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("name", pa.string()),
    pa.field("type", pa.string()),
    pa.field("source_path", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIMENSION)),
    pa.field("metadata", pa.string()),
])

TABLE_NAME = "notes"
ENTITIES_TABLE = "entities"


def _detect_table_dim(table) -> int | None:
    try:
        sample = table.to_pandas()
        if sample.empty:
            return None
        vec = sample["vector"].iloc[0]
        return len(vec) if vec is not None else None
    except Exception:
        return None


class VectorStore:
    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or os.environ.get("INDEX_PATH", ".vke_index")
        self._db = lancedb.connect(self._db_path)
        self._table = None
        self._entities_table = None
        self._migration_required = False
        self._ensure_tables()

    def _ensure_tables(self):
        if TABLE_NAME not in self._db.table_names():
            self._table = self._db.create_table(TABLE_NAME, schema=SCHEMA)
        else:
            self._table = self._db.open_table(TABLE_NAME)

        if ENTITIES_TABLE not in self._db.table_names():
            self._entities_table = self._db.create_table(ENTITIES_TABLE, schema=ENTITIES_SCHEMA)
        else:
            self._entities_table = self._db.open_table(ENTITIES_TABLE)

        # Validate embedding dimension on startup
        try:
            actual_dim = _detect_table_dim(self._table)
        except Exception as e:
            self._migration_required = True
            _logger.error("Cannot validate the notes index schema; refusing writes: %s", e)
            return

        if actual_dim != EMBEDDING_DIMENSION:
            self._migration_required = True
            _logger.error(
                "Notes index is %sd but the current embedding contract is %sd; "
                "leaving the existing table intact. Rebuild the index explicitly "
                "from the source notes before writing new vectors.",
                actual_dim,
                EMBEDDING_DIMENSION,
            )

    @contextmanager
    def _vector_operation(self, operation: str):
        outcome = "error"
        with observed_span(
            f"personalwiki.vector.{operation}",
            {"operation": operation},
        ):
            try:
                yield
            except BaseException:
                raise
            else:
                outcome = "success"
            finally:
                record_vector_operation(operation, outcome)

    def upsert(self, path: str, content: str, vector: list[float], metadata: dict | None = None):
        if self._migration_required:
            raise RuntimeError("Vector store migration required; refusing writes")
        import json
        import time
        with self._vector_operation("upsert"):
            self._table.add([{
                "path": path,
                "content": content,
                "vector": vector,
                "metadata": json.dumps(metadata or {}),
                "timestamp": int(time.time() * 1000),
            }])
            record_vector_upsert(1)

    def search(self, query_vector: list[float], limit: int = 10, filter_expr: str | None = None):
        with self._vector_operation("search"):
            query = self._table.search(query_vector).limit(limit)
            if filter_expr:
                query = query.where(filter_expr)
            results = query.to_list()
            record_vector_search(len(results))
            return results

    def search_entities(self, query_vector: list[float], limit: int = 10):
        with self._vector_operation("search_entities"):
            results = self._entities_table.search(query_vector).limit(limit).to_list()
            record_vector_search(len(results))
            return results

    def upsert_entity(self, entity_id: str, name: str, type_: str, source_path: str, vector: list[float], metadata: dict | None = None):
        if self._migration_required:
            raise RuntimeError("Vector store migration required; refusing writes")
        import json
        with self._vector_operation("upsert_entity"):
            self._entities_table.add([{
                "id": entity_id,
                "name": name,
                "type": type_,
                "source_path": source_path,
                "vector": vector,
                "metadata": json.dumps(metadata or {}),
            }])

    def delete(self, path: str):
        with self._vector_operation("delete"):
            self._table.delete(f"path = '{_escape_like(path)}'")

    def delete_entity(self, entity_id: str):
        with self._vector_operation("delete_entity"):
            self._entities_table.delete(f"id = '{_escape_like(entity_id)}'")

    def get_all_paths(self) -> list[str]:
        try:
            df = self._table.to_pandas()
            return df["path"].tolist() if not df.empty else []
        except Exception:
            return []

    def get_entity_by_name(self, name: str) -> dict | None:
        try:
            results = self._entities_table.search(name).where(f"name = '{_escape_like(name)}'").limit(1).to_list()
            return results[0] if results else None
        except Exception:
            return None


_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store
