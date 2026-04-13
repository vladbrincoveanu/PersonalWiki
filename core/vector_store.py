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

    def _get_links_for_paths(self, paths: list[str]) -> dict[str, list[str]]:
        """Fetch the links field from LanceDB for each path in the input list.

        Returns a dict mapping each input path to its list of linked paths.
        Missing paths are returned with empty lists.
        """
        if not paths:
            return {}
        # Fetch all rows (up to 1000) and filter by input paths
        all_rows = self._table.search().limit(1000).to_list()
        path_to_links = {}
        # Build index for O(1) lookup
        rows_by_path = {row["path"]: row for row in all_rows}
        for path in paths:
            row = rows_by_path.get(path)
            if row is not None:
                path_to_links[path] = row.get("links", [])
            else:
                path_to_links[path] = []
        return path_to_links

    def _graph_hop(
        self,
        paths: list[str],
        top_k: int = 5,
        hop1_weight: float = 0.5,
        hop2_weight: float = 0.25,
    ) -> list[dict]:
        """Traverse wikilinks from the top-k input paths.

        - Hop 1: Collect all links from the top-k paths.
        - Hop 2: From the hop-1 notes, collect their links too.
        - Score: hop-1 links get hop1_weight, hop-2 links get hop2_weight.
        - Deduplicate by path, sort by weight descending, return top-k.

        Returns list of {"path": str, "hop_weight": float} sorted by hop_weight descending.
        """
        if not paths:
            return []

        # Take top-k paths
        selected_paths = paths[:top_k]

        # Hop 1: get links from selected paths
        links_map = self._get_links_for_paths(selected_paths)
        hop1_links: list[str] = []
        for p in selected_paths:
            hop1_links.extend(links_map.get(p, []))

        # Hop 2: get links from hop-1 notes (deduplicated)
        hop1_unique = list(dict.fromkeys(hop1_links))  # preserve order, remove dups
        if hop1_unique:
            hop2_links_map = self._get_links_for_paths(hop1_unique)
            hop2_links: list[str] = []
            for p in hop1_unique:
                hop2_links.extend(hop2_links_map.get(p, []))
        else:
            hop2_links = []

        # Build weighted scores
        weights: dict[str, float] = {}
        for link in hop1_links:
            weights[link] = hop1_weight
        for link in hop2_links:
            # Only apply hop2_weight if not already scored as hop1
            if link not in weights:
                weights[link] = hop2_weight

        # Sort by weight descending, return top-k
        sorted_links = sorted(weights.items(), key=lambda x: x[1], reverse=True)
        return [{"path": path, "hop_weight": weight} for path, weight in sorted_links[:top_k]]


# Module-level singleton backed by config path
_store: VectorStore | None = None


def get_store() -> VectorStore:
    global _store
    if _store is None:
        from config import INDEX_PATH
        _store = VectorStore(INDEX_PATH)
    return _store
