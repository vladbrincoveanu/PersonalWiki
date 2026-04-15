# Hybrid Search Design (Phase 4)

**Date:** 2026-04-13
**Status:** Approved

---

## Overview

Add a `hybrid_search(query, top_k)` method to `VectorStore` that merges three retrieval streams via Reciprocal Rank Fusion (RRF): vector similarity (LanceDB), keyword matching (BM25Okapi), and graph contextual hopping (wikilink traversal). This delivers a "triple-threat" search without requiring Phase 2's graph database.

---

## Architecture

```
VectorStore
├── search(vector, top_k)         → pure LanceDB similarity (unchanged)
├── upsert(...)                   → existing upsert (unchanged)
└── hybrid_search(query, top_k)   → NEW: RRF merge of vector + BM25 + graph hops
```

**Three retrieval streams:**

| Stream | Source | Score basis |
|--------|--------|------------|
| Semantic | LanceDB vector search | cosine similarity |
| Keyword | rank-bm25 in-memory index | BM25 score |
| Graph hop | `links` field traversal | hop distance weight |

**RRF parameters:**
- `k = 60` (standard RRF constant)
- Vector weight: `1.0`
- BM25 weight: `0.9`
- Graph hop direct weight: `0.5`
- Graph hop second-level weight: `0.25`

---

## Component 1 — BM25 Index (`core/bm25_index.py`)

New module. Lazy-built in-memory index of all note texts, refreshed every 5 minutes.

```python
# Module-level state
_corpus: list[str]      # flattened text per note (frontmatter stripped)
_paths: list[str]      # corresponding source paths
_index: BM25Okapi | None
_last_built: float      # timestamp of last index build

def ensure_index() -> tuple[BM25Okapi, list[str], list[str]]:
    """Return (index, paths, corpus). Rebuilds if older than 5 minutes."""

def bm25_search(query: str, top_k: int) -> list[dict]:
    """Search BM25 index, return list of {path, score, rank}."""

def invalidate_index() -> None:
    """Force next search to rebuild the index."""
```

**Index building:**
1. Walk `NOTES_DIR/*.md`
2. Strip YAML frontmatter with `python-frontmatter`
3. Flatten body text (strip markdown syntax)
4. Tokenize with `rank_bm25` `SimpleTokenizer`
5. Build `BM25Okapi(tokenized_corpus)`

**Refresh strategy:** Lazy 5-minute TTL. First `bm25_search` call after TTL expiry triggers rebuild. No explicit invalidation on `upsert()` — stale index is acceptable for search quality at the cost of ~200ms rebuild time.

---

## Component 2 — Graph Hop (`core/vector_store.py`)

```python
def _graph_hop(paths: list[str], top_k: int = 5) -> list[dict]:
    """
    Traverse wikilinks from top_k vector results.
    Returns list of {path, hop_weight} for all linked notes.
    """
```

**Logic:**
1. Fetch top-k vector results → get their `links` arrays
2. Collect all unique linked paths
3. For second level: fetch those linked notes' `links` arrays too
4. Score: direct link from top-1 result = 0.5, from top-3 = 0.4, from hop-2 = 0.25
5. Deduplicate by path, sort descending by hop_weight
6. Return top-k results

---

## Component 3 — RRF Merge (`core/vector_store.py`)

```python
def hybrid_search(query: str, top_k: int = 5) -> list[dict]:
    """
    Unified search across vector, BM25, and graph hop streams.
    Returns list of {path, score, rank, metadata}.
    """
```

**RRF formula:**
```
score(path) = w_vector / (k + rank_vector(path))
            + w_bm25  / (k + rank_bm25(path))
            + w_hop   / (k + rank_hop(path))
```
Where missing ranks use `k * 2` (effectively zero contribution).

**Pipeline:**
1. `embed(query)` → vector search → `ranked_vector` (list of paths with ranks)
2. `ensure_index(); bm25_search(query)` → `ranked_bm25`
3. `_graph_hop(paths from ranked_vector)` → `ranked_hops`
4. Merge: for each unique path in union, compute RRF score
5. Sort descending, return top_k with score and metadata

---

## Return Format

`hybrid_search()` returns the same shape as `search()`:

```python
[
  {"path": "notes/pagedattention-paper.md", "score": 0.94, "rank": 1,
   "metadata": {"title": "PagedAttention Paper", "type": "paper", ...}},
  {"path": "notes/vllm-overview.md", "score": 0.87, "rank": 2,
   "metadata": {"title": "vLLM Overview", "type": "paper", ...}},
]
```

`score` is the raw RRF score (not normalized). `rank` is the final merged rank.

---

## File Changes

| File | Change |
|------|--------|
| `core/bm25_index.py` | **New** — BM25 singleton with lazy 5-min TTL |
| `core/vector_store.py` | Add `hybrid_search()`, `_graph_hop()`, `_build_rrf_score()` |
| `core/embeddings.py` | Already exports `embed()`, no change needed |
| `tests/test_vector_store.py` | Add `test_hybrid_search_vector_only`, `test_hybrid_search_bm25`, `test_hybrid_search_graph_hop`, `test_hybrid_search_rrf_merge` |

---

## Dependencies

```
rank-bm25
```

---

## Out of Scope

- Typed triple extraction (Phase 2) — graph hops use existing `links` wikilinks only
- Note format, frontmatter, or pipeline changes
- BM25 index persistence — rebuilt from disk on each refresh cycle
- Changes to `upsert()` invalidation — index rebuilds lazily on next search
- BM25 index refresh on every `upsert()` call

---

## Testing

| Test | Description |
|------|-------------|
| `test_hybrid_search_vector_only` | Query with no BM25 or graph matches — falls back to vector |
| `test_hybrid_search_bm25` | Exact-match keyword query returns BM25 result above vector |
| `test_hybrid_search_graph_hop` | Note linked to top result appears in results even without vector match |
| `test_hybrid_search_rrf_merge` | Combined query: RRF correctly boosts notes with multiple signal matches |
| `test_graph_hop_depth` | Only 1-hop and 2-hop links included, no deeper traversal |
| `test_bm25_index_refresh` | Index rebuilds after 5-min TTL expires |
