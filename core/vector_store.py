import json
from pathlib import Path
import lancedb
import pyarrow as pa

TABLE_NAME = "notes"

SCHEMA = pa.schema([
    pa.field("path", pa.string()),
    pa.field("text", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), 384)),
    pa.field("links", pa.list_(pa.string())),
    pa.field("metadata", pa.string()),
])


class VectorStore:
    def __init__(self, index_path: str | Path):
        self._db = lancedb.connect(str(index_path))
        if TABLE_NAME not in self._db.table_names():
            self._table = self._db.create_table(TABLE_NAME, schema=SCHEMA)
        else:
            self._table = self._db.open_table(TABLE_NAME)

    def upsert(self, path: str, text: str, vector: list[float], links: list[str], metadata: dict):
        try:
            self._table.delete(f"path = '{path}'")
        except Exception:
            pass
        self._table.add([{
            "path": path,
            "text": text,
            "vector": [float(v) for v in vector],
            "links": links,
            "metadata": json.dumps(metadata),
        }])

    def search(self, vector: list[float], top_k: int = 3) -> list[dict]:
        rows = self._table.search([float(v) for v in vector]).limit(top_k).to_list()
        results = []
        for row in rows:
            row["metadata"] = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
            results.append(row)
        return results

    def exists(self, path: str) -> bool:
        rows = self._table.search().where(f"path = '{path}'").limit(1).to_list()
        return len(rows) > 0

    def get_mtime(self, path: str) -> float:
        """Return stored mtime for a path, or 0.0 if not found."""
        rows = self._table.search().where(f"path = '{path}'").limit(1).to_list()
        if not rows:
            return 0.0
        meta = rows[0].get("metadata", "{}")
        if isinstance(meta, str):
            meta = json.loads(meta)
        return float(meta.get("_mtime", 0.0))


# Module-level singleton backed by config path
_store: VectorStore | None = None


def get_store() -> VectorStore:
    global _store
    if _store is None:
        from config import INDEX_PATH
        _store = VectorStore(INDEX_PATH)
    return _store
