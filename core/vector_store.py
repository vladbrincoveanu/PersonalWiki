import json
from pathlib import Path
import lancedb
import pyarrow as pa

TABLE_NAME = "notes"


def _escape_path(p: str) -> str:
    """Escape single quotes in path values for safe SQL interpolation."""
    return p.replace("'", "''")

SCHEMA = pa.schema([
    pa.field("path", pa.string()),
    pa.field("text", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), 384)),
    pa.field("links", pa.list_(pa.string())),
    pa.field("metadata", pa.string()),
])


def _rrf_merge(
    ranked_lists: list[list[dict]],
    weights: list[float],
    k: float = 60.0,
    top_k: int = 5,
    multi_signal_boost: float = 0.005,
) -> list[dict]:
    """
    Reciprocal Rank Fusion across N ranked lists.
    ranked_lists: list of lists, each sorted descending.
    weights: parallel list of weights per stream
    k: RRF constant (default 60)
    top_k: number of results to return
    multi_signal_boost: bonus added to paths appearing in 2+ streams (top-3 per stream)
    Returns: merged list of {path, score, rank} sorted by RRF score descending.
    """
    path_scores: dict[str, float] = {}

    # RRF accumulation
    for ranked_list, weight in zip(ranked_lists, weights):
        for item in ranked_list:
            path = item["path"]
            rank = item.get("rank")
            if rank is None:
                rank = k * 2
            rrf_score = weight / (k + rank)
            path_scores[path] = path_scores.get(path, 0.0) + rrf_score

    # Multi-signal boost: reward notes appearing in multiple streams
    path_stream_count: dict[str, int] = {}
    for ranked_list in ranked_lists:
        for item in ranked_list[:3]:  # top-3 per stream
            path_stream_count[item["path"]] = path_stream_count.get(item["path"], 0) + 1

    for path, count in path_stream_count.items():
        if count >= 2:
            path_scores[path] += multi_signal_boost * (count - 1)

    # Sort and return top_k
    sorted_paths = sorted(path_scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {"path": path, "score": score, "rank": rank}
        for rank, (path, score) in enumerate(sorted_paths[:top_k], start=1)
    ]


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

    def hybrid_search(self, query: str, top_k: int = 5, min_score: float = 0.001) -> list[dict]:
        """
        Unified search across vector, BM25, and graph hop streams via RRF.
        Returns list of {path, score, rank, metadata} sorted by RRF score descending.
        """
        from core.embeddings import embed
        from core.bm25_index import ensure_index, bm25_search

        # Vector stream: embed + search with doubled top_k for headroom
        query_vector = embed(query)
        vector_results = self.search(query_vector, top_k=top_k * 2)

        # BM25 stream
        ensure_index()
        bm25_results = bm25_search(query, top_k=top_k * 2)

        # Graph hops from vector results
        vector_paths = [r["path"] for r in vector_results]
        hop_results = self._graph_hop(vector_paths, top_k=top_k * 2)
        # Convert hop_weight to rank-based scoring for RRF
        ranked_hops = [
            {"path": item["path"], "score": item["hop_weight"], "rank": rank}
            for rank, item in enumerate(hop_results, start=1)
        ]

        # Enumerate ranks for vector results so they are differentiated in RRF
        ranked_vector = [
            {"path": r["path"], "score": r.get("score"), "rank": rank + 1}
            for rank, r in enumerate(vector_results)
        ]

        # Collect metadata from ALL streams before merging
        metadata_map: dict[str, dict] = {}
        for r in vector_results:
            metadata_map[r["path"]] = r.get("metadata", {})
        for r in bm25_results:
            if r["path"] not in metadata_map:
                metadata_map[r["path"]] = {}
        for r in hop_results:
            if r["path"] not in metadata_map:
                metadata_map[r["path"]] = {}

        # RRF merge
        merged = _rrf_merge(
            [ranked_vector, bm25_results, ranked_hops],
            weights=[1.0, 0.9, 0.5],
            k=60,
            top_k=top_k,
        )

        # Filter noise — if top result scores below threshold, return empty
        if merged and merged[0]["score"] < min_score:
            return []

        # Attach metadata from collected map
        for item in merged:
            item["metadata"] = metadata_map.get(item["path"], {})

        return merged

    def _get_links_for_paths(self, paths: list[str]) -> dict[str, list[str]]:
        """Fetch the links field from LanceDB for each path in the input list.

        Returns a dict mapping each input path to its list of linked paths.
        Missing paths are returned with empty lists.
        """
        if not paths:
            return {}
        # Build path filter to fetch only the rows we need
        path_filter = " OR ".join(f"path = '{_escape_path(p)}'" for p in paths)
        all_rows = self._table.search().where(path_filter).to_list()
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
            if link not in weights:
                # Only apply hop2_weight if not already scored as hop1
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
