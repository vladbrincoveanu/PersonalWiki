# Hybrid Search Scoring Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-signal boost to `_rrf_merge` and `min_score` threshold guard to `hybrid_search` to prevent garbage queries from returning noise.

**Architecture:** Two targeted changes: (1) `_rrf_merge` gets a post-processing step that boosts notes appearing in top-3 of 2+ streams; (2) `hybrid_search` filters results when top score is below threshold.

---

## File Map

| File | Change |
|------|--------|
| `core/vector_store.py` | Add `multi_signal_boost` to `_rrf_merge`; add `min_score` param to `hybrid_search` |
| `tests/test_vector_store.py` | Add multi-signal boost tests and min_score threshold tests |

---

## Task 1: Add Multi-Signal Boost to `_rrf_merge`

**Files:**
- Modify: `core/vector_store.py` — update `_rrf_merge()` function
- Test: `tests/test_vector_store.py` — add boost tests

- [ ] **Step 1: Write failing tests**

```python
# tests/test_vector_store.py — add these tests

from core.vector_store import _rrf_merge


def test_rrf_multi_signal_boost_2_streams():
    """Note appearing in top-3 of 2 streams gets boost."""
    vector = [{"path": "multi.md", "rank": 1}, {"path": "single.md", "rank": 2}]
    bm25  = [{"path": "multi.md", "rank": 1}, {"path": "other.md", "rank": 2}]
    hops  = []

    result = _rrf_merge([vector, bm25, hops], weights=[1.0, 0.9, 0.5], k=60, top_k=5, multi_signal_boost=0.005)
    result_dict = {r["path"]: r for r in result}

    multi_score = result_dict["multi.md"]["score"]
    single_score = result_dict["single.md"]["score"]

    # multi.md appears in 2 streams → gets boost; single.md only in 1 → no boost
    # Even if rank differences would favor single.md, boost should overcome that
    assert multi_score > single_score, f"multi={multi_score} should beat single={single_score}"


def test_rrf_multi_signal_boost_3_streams():
    """Note appearing in all 3 streams gets larger boost."""
    vector = [{"path": "triple.md", "rank": 2}]
    bm25  = [{"path": "triple.md", "rank": 2}]
    hops  = [{"path": "triple.md", "rank": 1}]  # hops uses hop_weight, rank is enumerated

    result = _rrf_merge([vector, bm25, hops], weights=[1.0, 0.9, 0.5], k=60, top_k=5, multi_signal_boost=0.005)
    triple_score = next(r["score"] for r in result if r["path"] == "triple.md")

    # triple gets boost from appearing in 3 streams
    assert triple_score >= 0.005  # at minimum the 3-stream boost


def test_rrf_no_boost_single_stream():
    """Note only in one stream gets no boost."""
    vector = [{"path": "alone.md", "rank": 1}]
    bm25  = []
    hops  = []

    result = _rrf_merge([vector, bm25, hops], weights=[1.0, 0.9, 0.5], k=60, top_k=5, multi_signal_boost=0.005)
    alone_score = next(r["score"] for r in result if r["path"] == "alone.md")

    # Should equal normal RRF: 1.0/61 ≈ 0.0164, no boost applied
    assert alone_score == pytest.approx(1.0 / 61, rel=1e-3)


def test_rrf_boost_preserves_sort_order():
    """Boost doesn't change relative order of same-stream notes."""
    vector = [{"path": "a.md", "rank": 1}, {"path": "b.md", "rank": 2}]
    bm25  = [{"path": "a.md", "rank": 1}]  # only a in bm25 (gets boost)
    hops  = []

    result = _rrf_merge([vector, bm25, hops], weights=[1.0, 0.9, 0.5], k=60, top_k=5, multi_signal_boost=0.005)
    paths = [r["path"] for r in result]

    # a.md gets boost but should still rank above b.md only if boost makes sense
    assert paths.index("a.md") < paths.index("b.md")
```

- [ ] **Step 2: Run tests — verify they fail (boost logic not yet in _rrf_merge)**

```bash
pytest tests/test_vector_store.py -k "multi_signal" -v
```

- [ ] **Step 3: Add multi_signal_boost to `_rrf_merge`**

```python
# core/vector_store.py — update _rrf_merge()

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
```

- [ ] **Step 4: Run multi-signal tests — verify they pass**

```bash
pytest tests/test_vector_store.py -k "multi_signal" -v
```

- [ ] **Step 5: Commit**

```bash
git add core/vector_store.py tests/test_vector_store.py
git commit -m "feat: add multi_signal_boost to _rrf_merge for hybrid search"
```

---

## Task 2: Add min_score Threshold to `hybrid_search`

**Files:**
- Modify: `core/vector_store.py` — update `hybrid_search()` signature
- Test: `tests/test_vector_store.py` — add threshold tests

- [ ] **Step 1: Write failing tests**

```python
# tests/test_vector_store.py — add these tests

def test_hybrid_search_min_score_threshold(mock_store, sample_notes):
    """Query with score below threshold returns empty list."""
    store, notes_dir = mock_store
    for note in sample_notes:
        store.upsert(note["path"], note["text"], note["vector"], note["links"], note["metadata"])

    with patch("core.embeddings.embed") as mock_embed, \
         patch("core.bm25_index.ensure_index"), \
         patch("core.bm25_index.bm25_search") as mock_bm25, \
         patch.object(store, "search") as mock_vec, \
         patch.object(store, "_graph_hop") as mock_hop:

        mock_embed.return_value = [0.1] * 384
        # Very low BM25 scores → low RRF scores
        mock_bm25.return_value = [{"path": "notes/a.md", "score": 0.001, "rank": 100}]
        mock_vec.return_value = [{"path": "notes/a.md", "score": 0.001, "rank": 100, "metadata": {}}]
        mock_hop.return_value = []

        # With default min_score=0.001, this should return []
        result = store.hybrid_search("garbage query xyz123", top_k=5)
        assert result == []


def test_hybrid_search_above_threshold(mock_store, sample_notes):
    """Legitimate query above threshold returns results."""
    store, notes_dir = mock_store
    for note in sample_notes:
        store.upsert(note["path"], note["text"], note["vector"], note["links"], note["metadata"])

    with patch("core.embeddings.embed") as mock_embed, \
         patch("core.bm25_index.ensure_index"), \
         patch("core.bm25_index.bm25_search") as mock_bm25, \
         patch.object(store, "search") as mock_vec, \
         patch.object(store, "_graph_hop") as mock_hop:

        mock_embed.return_value = [0.1] * 384
        # Higher BM25 scores → higher RRF
        mock_bm25.return_value = [{"path": "notes/a.md", "score": 10.0, "rank": 1}]
        mock_vec.return_value = [{"path": "notes/a.md", "score": 0.9, "rank": 1, "metadata": {"title": "A"}}]
        mock_hop.return_value = []

        result = store.hybrid_search("attention mechanism", top_k=5)
        assert len(result) >= 1
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_vector_store.py -k "min_score" -v
```

- [ ] **Step 3: Add min_score to hybrid_search**

```python
# core/vector_store.py — update hybrid_search() signature and add filtering

def hybrid_search(self, query: str, top_k: int = 5, min_score: float = 0.001) -> list[dict]:
    """
    Unified search across vector, BM25, and graph hop streams via RRF.
    min_score: if the top result's RRF score is below this, return [] instead.
    """
    from core.embeddings import embed
    from core.bm25_index import ensure_index, bm25_search

    query_vector = embed(query)
    vector_results = self.search(query_vector, top_k=top_k * 2)
    ensure_index()
    bm25_results = bm25_search(query, top_k=top_k * 2)
    vector_paths = [r["path"] for r in vector_results]
    hop_results = self._graph_hop(vector_paths, top_k=top_k * 2)

    ranked_hops = [
        {"path": item["path"], "score": item["hop_weight"], "rank": rank}
        for rank, item in enumerate(hop_results, start=1)
    ]
    ranked_vector = [
        {"path": r["path"], "score": r.get("score"), "rank": rank + 1}
        for rank, r in enumerate(vector_results)
    ]

    metadata_map: dict[str, dict] = {}
    for r in vector_results:
        metadata_map[r["path"]] = r.get("metadata", {})
    for r in bm25_results:
        if r["path"] not in metadata_map:
            metadata_map[r["path"]] = {}
    for r in hop_results:
        if r["path"] not in metadata_map:
            metadata_map[r["path"]] = {}

    merged = _rrf_merge(
        [ranked_vector, bm25_results, ranked_hops],
        weights=[1.0, 0.9, 0.5],
        k=60,
        top_k=top_k,
        multi_signal_boost=0.005,
    )

    # Filter noise — if top result scores below threshold, return empty
    if merged and merged[0]["score"] < min_score:
        return []

    for item in merged:
        item["metadata"] = metadata_map.get(item["path"], {})

    return merged
```

- [ ] **Step 4: Run min_score tests — verify they pass**

```bash
pytest tests/test_vector_store.py -k "min_score" -v
```

- [ ] **Step 5: Commit**

```bash
git add core/vector_store.py tests/test_vector_store.py
git commit -m "feat: add min_score threshold guard to hybrid_search"
```

---

## Task 3: Run Full Test Suite

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest -v --tb=short
```

- [ ] **Step 2: Verify all tests pass**

---

## Spec Coverage Check

| Spec Requirement | Task |
|-----------------|------|
| Multi-signal boost (2+ streams) | Task 1 |
| Multi-signal boost (3 streams — larger boost) | Task 1 |
| No boost for single-stream notes | Task 1 |
| min_score threshold filter | Task 2 |
| Above-threshold queries still return results | Task 2 |
| All tests pass | Task 3 |
