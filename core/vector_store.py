import json
from pathlib import Path
import lancedb
import logging
import pyarrow as pa

TABLE_NAME = "notes"
ENTITIES_TABLE = "personal_entities"

ENTITIES_SCHEMA = pa.schema([
    pa.field("path", pa.string()),
    pa.field("entity_type", pa.string()),
    pa.field("entity_name", pa.string()),
    pa.field("summary", pa.string()),
    pa.field("metadata", pa.string()),
])


def _escape_path(p: str) -> str:
    """Escape single quotes in path values for safe SQL interpolation."""
    return p.replace("'", "''")


def _parse_metadata(meta: str | dict) -> dict:
    """Parse metadata from JSON string or return as-is if already a dict."""
    return json.loads(meta) if isinstance(meta, str) else meta


_logger = logging.getLogger(__name__)

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


def _detect_table_dim(table) -> int:
    """Read vector field dimension from an open LanceDB table schema."""
    schema = table.schema
    vector_field = schema.field("vector")
    return vector_field.type.list_size


class VectorStore:
    def __init__(self, index_path: str | Path):
        self._db = lancedb.connect(str(index_path))
        if TABLE_NAME not in self._db.table_names():
            self._table = self._db.create_table(TABLE_NAME, schema=SCHEMA)
        else:
            self._table = self._db.open_table(TABLE_NAME)

        if ENTITIES_TABLE not in self._db.table_names():
            self._entities_table = self._db.create_table(ENTITIES_TABLE, schema=ENTITIES_SCHEMA)
        else:
            self._entities_table = self._db.open_table(ENTITIES_TABLE)

        self._migrate_if_needed()

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
                    _logger.warning("Index cleared. Run `python -m vault.scanner` to rebuild.")
            except Exception as e:
                _logger.debug(f"Skipping migration check for '{table_name}': {e}")

        global _store
        _store = None

    def upsert(self, path: str, text: str, vector: list[float], links: list[str], metadata: dict):
        self._table.delete(f"path = '{_escape_path(path)}'")
        if len(vector) != 384:
            raise ValueError(f"Vector dimension must be 384, got {len(vector)}")
        self._table.add([{
            "path": path,
            "text": text,
            "vector": [float(v) for v in vector],
            "links": links,
            "metadata": json.dumps(metadata),
        }])

    def delete(self, path: str) -> bool:
        """Delete a path from the vector store. Returns True if a row was deleted."""
        try:
            self._table.delete(f"path = '{_escape_path(path)}'")
            return True
        except Exception:
            return False

    def search(self, vector: list[float], top_k: int = 3) -> list[dict]:
        rows = self._table.search([float(v) for v in vector]).limit(top_k).to_list()
        results = []
        for row in rows:
            row["metadata"] = _parse_metadata(row["metadata"])
            results.append(row)
        return results

    def exists(self, path: str) -> bool:
        rows = self._table.search().where(f"path = '{_escape_path(path)}'").limit(1).to_list()
        return len(rows) > 0

    def get_title_by_url(self, url: str) -> str | None:
        """Return the stored note title for a URL, or None if not found."""
        try:
            rows = self._table.search().where(f"path = '{_escape_path(url)}'").limit(1).to_list()
            if not rows:
                return None
            metadata = _parse_metadata(rows[0].get("metadata", "{}"))
            return metadata.get("title")
        except Exception:
            return None

    def get_all_paths(self) -> list[str]:
        """Return all indexed URLs/paths."""
        try:
            return [_escape_path(row["path"]) for row in self._table.to_list() if row.get("path")]
        except Exception:
            return []

    def get_mtime(self, path: str) -> float:
        """Return stored mtime for a path, or 0.0 if not found."""
        rows = self._table.search().where(f"path = '{_escape_path(path)}'").limit(1).to_list()
        if not rows:
            return 0.0
        meta = _parse_metadata(rows[0].get("metadata", "{}"))
        return float(meta.get("_mtime", 0.0))

    def upsert_entity(self, path: str, entity_type: str, entity_name: str, summary: str, metadata: dict):
        try:
            self._entities_table.delete(f"path = '{_escape_path(path)}' AND entity_name = '{entity_name}'")
        except Exception:
            pass
        self._entities_table.add([{
            "path": path,
            "entity_type": entity_type,
            "entity_name": entity_name,
            "summary": summary,
            "metadata": json.dumps(metadata),
        }])

    def search_entities(self, query: str, entity_type: str | None = None, top_k: int = 5) -> list[dict]:
        from core.embeddings import embed
        query_vector = embed(query)
        if entity_type:
            results = self._entities_table.search([float(v) for v in query_vector]).where(f"entity_type = '{entity_type}'").limit(top_k).to_list()
        else:
            results = self._entities_table.search([float(v) for v in query_vector]).limit(top_k).to_list()
        for row in results:
            row["metadata"] = _parse_metadata(row["metadata"])
        return results

    def get_recent_notes(self, top_k: int = 5) -> list[dict]:
        """Return notes sorted by _indexed_at timestamp descending."""
        all_rows = self._table.to_list()
        sorted_rows = sorted(
            all_rows,
            key=lambda r: _parse_metadata(r.get("metadata", "{}")).get("_indexed_at", 0),
            reverse=True
        )
        return [{"path": r["path"], "metadata": _parse_metadata(r.get("metadata", "{}"))} for r in sorted_rows[:top_k]]

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

        # Track D: Cross-encoder rerank — improve result ordering
        from core.reranker import CrossEncoderReranker
        reranker = CrossEncoderReranker()
        reranked = reranker.rerank(query, merged, top_k=top_k)
        return reranked

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
