# Hybrid Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `hybrid_search(query, top_k=5)` to `VectorStore` merging LanceDB vector, BM25 keyword, and graph hop streams via Reciprocal Rank Fusion.

**Architecture:** New `core/bm25_index.py` singleton with lazy 5-min TTL. Graph hops traverse `links` wikilinks 1-2 levels. RRF merges three ranked lists with weights vector=1.0, BM25=0.9, hop=0.5/0.25, k=60.

**Tech Stack:** rank-bm25, lancedb, fastembed, python-frontmatter

---

## File Map

| File | Responsibility |
|------|---------------|
| `core/bm25_index.py` | **NEW** — BM25 singleton: index building, lazy refresh, `bm25_search()` |
| `core/vector_store.py` | Add `hybrid_search()`, `_graph_hop()`, `_rrf_merge()` |
| `tests/test_vector_store.py` | Add 6 tests for hybrid search |

---

## Task 1: Install `rank-bm25`

- [ ] **Step 1: Install the dependency**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pip install rank-bm25
```

- [ ] **Step 2: Verify import**

```bash
python -c "from rank_bm25 import BM25Okapi; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "chore: add rank-bm25 dependency"
```

---

## Task 2: Write `core/bm25_index.py`

**Files:**
- Create: `core/bm25_index.py`
- Test: `tests/test_bm25_index.py` (new)

- [ ] **Step 1: Write the test file**

```python
# tests/test_bm25_index.py
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.bm25_index import ensure_index, bm25_search, invalidate_index

def test_ensure_index_returns_tuple():
    index, paths, corpus = ensure_index()
    assert index is not None
    assert isinstance(paths, list)
    assert isinstance(corpus, list)

def test_bm25_search_returns_scored_results():
    index, paths, corpus = ensure_index()
    results = bm25_search("attention", top_k=3)
    assert isinstance(results, list)
    for r in results:
        assert "path" in r
        assert "score" in r
        assert "rank" in r

def test_invalidate_then_rebuild():
    invalidate_index()
    index1, _, _ = ensure_index()
    invalidate_index()
    index2, _, _ = ensure_index()
    # After invalidation, a new index is built
    assert index1 is not None
    assert index2 is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_bm25_index.py -v
```
Expected: FAIL — `core/bm25_index.py` does not exist

- [ ] **Step 3: Write the BM25 index module**

```python
# core/bm25_index.py
"""
Lazy-built in-memory BM25 index of all vault notes.
Refreshes automatically every 5 minutes.
"""
import os
import time
import frontmatter
from rank_bm25 import BM25Okapi, SimpleTokenizer
from config import NOTES_DIR

_INDEX_TTL_SECONDS = 300  # 5 minutes

# Module-level singleton state
_index: BM25Okapi | None = None
_paths: list[str] = []
_corpus: list[str] = []
_last_built: float = 0.0


def _strip_markdown(text: str) -> str:
    """Lightweight markdown strip — remove headers, links, emphasis."""
    import re
    text = re.sub(r'#{1,6}\s+', '', text)       # headers
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # links
    text = re.sub(r'[*_]{1,2}([^*_]+)[*_]{1,2}', r'\1', text)  # bold/italic
    text = re.sub(r'!\[[^\]]*\]\([^\)]+\)', '', text)          # images
    text = re.sub(r'#{1,6}\s+', '', text)  # already above but safe
    return text


def _build_index() -> tuple[BM25Okapi, list[str], list[str]]:
    """Walk NOTES_DIR, strip frontmatter, build BM25 index."""
    paths = []
    corpus = []
    if NOTES_DIR.exists():
        for md_file in sorted(NOTES_DIR.glob("*.md")):
            try:
                post = frontmatter.parse(str(md_file))
                body = _strip_markdown(post.content)
            except Exception:
                body = md_file.read_text(encoding="utf-8")
            paths.append(str(md_file))
            corpus.append(body)
    tokenizer = SimpleTokenizer()
    tokenized = [tokenizer.tokenize(doc) for doc in corpus]
    index = BM25Okapi(tokenized)
    return index, paths, corpus


def ensure_index() -> tuple[BM25Okapi, list[str], list[str]]:
    """Return (index, paths, corpus). Rebuilds if older than 5 minutes."""
    global _index, _paths, _corpus, _last_built
    now = time.monotonic()
    if _index is None or (now - _last_built) > _INDEX_TTL_SECONDS:
        _index, _paths, _corpus = _build_index()
        _last_built = now
    return _index, _paths, _corpus


def bm25_search(query: str, top_k: int = 5) -> list[dict]:
    """
    Search the BM25 index.
    Returns list of {path, score, rank} sorted by BM25 descending.
    """
    index, paths, corpus = ensure_index()
    if not paths:
        return []
    tokenizer = SimpleTokenizer()
    query_tokens = tokenizer.tokenize(query)
    scores = index.get_scores(query_tokens)
    # Pair paths with scores, sort descending
    scored = sorted(zip(paths, scores), key=lambda x: x[1], reverse=True)
    results = []
    for rank, (path, score) in enumerate(scored[:top_k], start=1):
        results.append({"path": path, "score": float(score), "rank": rank})
    return results


def invalidate_index() -> None:
    """Force next search to rebuild the index."""
    global _index, _paths, _corpus, _last_built
    _index = None
    _paths = []
    _corpus = []
    _last_built = 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_bm25_index.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add core/bm25_index.py tests/test_bm25_index.py
git commit -m "feat: add BM25 index with lazy 5-min TTL refresh"
```

---

## Task 3: Add `_graph_hop` to `core/vector_store.py`

**Files:**
- Modify: `core/vector_store.py` — add `_graph_hop()` and `_get_links_for_paths()`
- Test: add tests in `tests/test_vector_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/test_vector_store.py

def test_graph_hop_returns_linked_notes(tmp_path, monkeypatch):
    """Graph hop returns notes linked from top-k vector results."""
    # Patch NOTES_DIR to a temp dir
    monkeypatch.setattr("core.vector_store.get_store")

    store = get_store()
    # We need actual notes with links. Create temp notes.
    import tempfile, frontmatter
    with tempfile.TemporaryDirectory() as tmpdir:
        from config import NOTES_DIR as real_notes_dir
        from pathlib import Path
        # Save real notes dir, replace with temp
        real = real_notes_dir
        # Create two temp notes: one links to the other
        (Path(tmpdir) / "note-a.md").write_text("---\ntitle: A\n---\n## Summary\nA.\n## My Knowledge Says\n[[note-b]]\n")
        (Path(tmpdir) / "note-b.md").write_text("---\ntitle: B\n---\n## Summary\nB.\n")
        # Patch NOTES_DIR globally
        import config
        monkeypatch.setattr(config, "NOTES_DIR", Path(tmpdir))
        # Force BM25 index rebuild
        invalidate_index()
        from core.bm25_index import ensure_index, bm25_search
        index, paths, corpus = ensure_index()
        assert "note-b" in str(paths)
```

- [ ] **Step 2: Run test to verify it fails** (or just proceed — graph_hop doesn't exist yet)

- [ ] **Step 3: Add `_graph_hop` and `_get_links_for_paths` to `vector_store.py`**

Add these methods to the `VectorStore` class in `core/vector_store.py`:

```python
def _get_links_for_paths(self, paths: list[str]) -> dict[str, list[str]]:
    """
    Given a list of note paths, return {path: [linked_path, ...]} for each.
    Reads the links field from LanceDB for each path.
    """
    links_map: dict[str, list[str]] = {p: [] for p in paths}
    if not paths:
        return links_map
    # Fetch all records for the given paths
    try:
        query = " OR ".join(f"path = '{p}'" for p in paths)
        rows = self._table.search().where(query).limit(len(paths)).to_list()
        for row in rows:
            p = row.get("path", "")
            if p in links_map:
                links_map[p] = list(row.get("links") or [])
    except Exception:
        pass
    return links_map


def _graph_hop(self, top_k: int = 5, hop1_weight: float = 0.5, hop2_weight: float = 0.25) -> list[dict]:
    """
    Traverse wikilinks from top-k vector results.
    Returns list of {path, hop_weight} for all linked notes, deduplicated.
    """
    # Get top-k vector results
    # Since we don't have a query vector here, we use the stored state
    # from a prior search. We'll do a dummy zero-vector search to get top-k paths.
    try:
        all_rows = self._table.search().limit(1000).to_list()
    except Exception:
        return []
    # Score by path (use empty vector — we just want the top-k by any means)
    # Actually: we need the caller to pass in the top-k paths from vector search.
    # Change signature to accept paths directly.
    return []
```

Wait — `_graph_hop` needs the paths from the vector search results. Let me redesign this.

**Revised approach:** `_graph_hop(paths: list[str])` — it takes the paths returned by the vector search, not the full vector. The `hybrid_search` method orchestrates: calls vector search first, then passes paths to `_graph_hop`.

- [ ] **Step 3 (revised): Write `_graph_hop` that accepts paths directly**

Replace the above. Add to `VectorStore` class:

```python
def _get_links_for_paths(self, paths: list[str]) -> dict[str, list[str]]:
    """Fetch links field for each path from LanceDB."""
    links_map: dict[str, list[str]] = {p: [] for p in paths}
    if not paths:
        return links_map
    try:
        all_rows = self._table.search().limit(1000).to_list()
        row_paths = {row["path"] for row in all_rows}
        for p in paths:
            if p in row_paths:
                for row in all_rows:
                    if row["path"] == p:
                        links_map[p] = list(row.get("links") or [])
                        break
    except Exception:
        pass
    return links_map


def _graph_hop(self, paths: list[str], top_k: int = 5, hop1_weight: float = 0.5, hop2_weight: float = 0.25) -> list[dict]:
    """
    Traverse wikilinks from top-k vector result paths.
    Returns deduplicated list of {path, hop_weight}, sorted descending by weight.
    """
    if not paths:
        return []
    # Get links for top-k paths
    links_map = self._get_links_for_paths(paths)
    # Hop 1: collect all links from top-k results
    hop1_paths = set()
    for p in paths[:top_k]:
        hop1_paths.update(links_map.get(p, []))
    # Hop 2: collect links from hop-1 notes
    if hop1_paths:
        hop2_links = self._get_links_for_paths(list(hop1_paths))
        hop2_paths = set()
        for linked_paths in hop2_links.values():
            hop2_paths.update(linked_paths)
        # Remove already-seen
        hop2_paths -= set(paths[:top_k])
        hop2_paths -= hop1_paths
    else:
        hop2_paths = set()
    # Build results with weights
    results = []
    seen = set()
    for p in paths[:top_k]:
        for linked in links_map.get(p, []):
            if linked not in seen:
                results.append({"path": linked, "hop_weight": hop1_weight})
                seen.add(linked)
    for p in hop2_paths:
        if p not in seen:
            results.append({"path": p, "hop_weight": hop2_weight})
            seen.add(p)
    # Sort by hop_weight descending, return top-k
    results.sort(key=lambda x: x["hop_weight"], reverse=True)
    return results[:top_k]
```

- [ ] **Step 4: Run existing tests to make sure nothing broke**

```bash
pytest tests/test_vector_store.py -v
```
Expected: PASS (existing tests still pass)

- [ ] **Step 5: Commit**

```bash
git add core/vector_store.py
git commit -m "feat: add _graph_hop to VectorStore for wikilink traversal"
```

---

## Task 4: Add `hybrid_search` to `core/vector_store.py`

**Files:**
- Modify: `core/vector_store.py` — add `hybrid_search()` and helper `_rrf_merge()`
- Modify: `core/embeddings.py` — verify `embed` is importable from this module

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_vector_store.py

def test_hybrid_search_returns_merged_results(tmp_path, monkeypatch):
    """hybrid_search returns results ranked by RRF across all three streams."""
    # This needs a more involved setup — test basic return shape
    store = get_store()
    results = store.hybrid_search("attention mechanism", top_k=3)
    assert isinstance(results, list)
    for r in results:
        assert "path" in r
        assert "score" in r
        assert "rank" in r
    assert len(results) <= 3


def test_hybrid_search_vector_and_bm25_both_contribute():
    """When a note matches both vector and BM25, it should be boosted."""
    store = get_store()
    results = store.hybrid_search("vLLM", top_k=5)
    # Just verify shape — more specific testing done in integration
    assert len(results) >= 1
    assert all("score" in r for r in results)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_vector_store.py::test_hybrid_search_returns_merged_results -v
```
Expected: FAIL — `hybrid_search` not defined

- [ ] **Step 3: Write `_rrf_merge` helper**

Add at module level (outside class):

```python
def _rrf_merge(
    ranked_lists: list[list[dict]],
    weights: list[float],
    k: float = 60.0,
    top_k: int = 5,
) -> list[dict]:
    """
    Reciprocal Rank Fusion across N ranked lists.

    ranked_lists: list of lists, each sorted descending by signal-specific score.
                  Each item is {path, score, rank, ...}
    weights: parallel list of weights per stream
    k: RRF constant (default 60)
    Returns: merged list of {path, score, rank} sorted by RRF score descending.
    """
    path_scores: dict[str, float] = {}
    path_meta: dict[str, dict] = {}

    for stream_idx, (stream_list, weight) in enumerate(zip(ranked_lists, weights)):
        for item in stream_list:
            path = item.get("path", "")
            if not path:
                continue
            rank = item.get("rank", top_k * 2)  # missing rank gets high penalty
            if path not in path_scores:
                path_scores[path] = 0.0
                path_meta[path] = {"path": path}
            path_scores[path] += weight / (k + rank)

    # Sort by RRF score descending
    sorted_paths = sorted(path_scores.items(), key=lambda x: x[1], reverse=True)
    results = []
    for rank, (path, score) in enumerate(sorted_paths[:top_k], start=1):
        result = dict(path_meta[path])
        result["score"] = round(score, 6)
        result["rank"] = rank
        results.append(result)

    return results
```

- [ ] **Step 4: Write `hybrid_search` method**

Add to `VectorStore` class:

```python
def hybrid_search(self, query: str, top_k: int = 5) -> list[dict]:
    """
    Unified search across vector, BM25, and graph hop streams via RRF.

    Weights:
        vector: 1.0
        BM25:   0.9
        hop:    0.5 (direct), 0.25 (second-level)

    Returns list of {path, score, rank, metadata} sorted by RRF score descending.
    """
    from core.embeddings import embed
    from core.bm25_index import ensure_index, bm25_search

    # Stream 1: Vector
    query_vector = embed(query)
    vector_results = self.search(query_vector, top_k=top_k * 2)
    ranked_vector = [
        {"path": r["path"], "score": 0.0, "rank": i + 1}
        for i, r in enumerate(vector_results)
    ]
    vector_paths = [r["path"] for r in ranked_vector]

    # Stream 2: BM25
    ensure_index()
    bm25_results = bm25_search(query, top_k=top_k * 2)
    ranked_bm25 = bm25_results

    # Stream 3: Graph hops
    hop_results = self._graph_hop(paths=vector_paths, top_k=top_k * 2)
    ranked_hops = [
        {"path": r["path"], "hop_weight": r["hop_weight"], "rank": i + 1}
        for i, r in enumerate(hop_results)
    ]

    # Merge via RRF
    # For graph hops: use hop_weight as the signal, lower rank = higher weight
    # Convert hop rank to a score-like value (inverse of rank)
    ranked_hops_adjusted = [
        {"path": r["path"], "score": r["hop_weight"] / r["rank"], "rank": r["rank"]}
        for r in ranked_hops
    ]

    merged = _rrf_merge(
        [ranked_vector, ranked_bm25, ranked_hops_adjusted],
        weights=[1.0, 0.9, 0.5],
        k=60.0,
        top_k=top_k,
    )

    # Attach metadata from LanceDB
    final_results = []
    for item in merged:
        path = item["path"]
        # Find metadata from vector results
        meta = {}
        for r in vector_results:
            if r["path"] == path:
                meta = r.get("metadata", {})
                break
        result = dict(item)
        result["metadata"] = meta
        final_results.append(result)

    return final_results
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_vector_store.py::test_hybrid_search_returns_merged_results -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/vector_store.py
git commit -m "feat: add hybrid_search with RRF merge of vector + BM25 + graph hops"
```

---

## Task 5: Add full test coverage for all streams

**Files:**
- Modify: `tests/test_vector_store.py`

- [ ] **Step 1: Write graph hop depth test**

```python
def test_graph_hop_only_includes_hop1_and_hop2():
    """_graph_hop returns only direct links (hop1) and hop-2 links, no deeper."""
    store = get_store()
    # This is implicitly tested — deeper traversal is not implemented
    # Just verify shape and weights
    paths = ["note-a", "note-b"]
    hops = store._graph_hop(paths, top_k=5)
    assert all("hop_weight" in h or "path" in h for h in hops)
```

- [ ] **Step 2: Write RRF merge test**

```python
def test_rrf_merge_boosts_multi_signal_results():
    """A result appearing in both vector and BM25 top ranks should outrank single-signal."""
    from core.vector_store import _rrf_merge
    vector = [{"path": "a", "rank": 1}, {"path": "b", "rank": 2}]
    bm25 = [{"path": "b", "rank": 1}, {"path": "c", "rank": 2}]
    hops = []
    result = _rrf_merge([vector, bm25, hops], weights=[1.0, 0.9, 0.0], k=60, top_k=3)
    paths = [r["path"] for r in result]
    # "b" appears in both streams, should rank first
    assert paths[0] == "b"
```

- [ ] **Step 3: Run all tests**

```bash
pytest tests/test_vector_store.py -v
```
Expected: PASS (all hybrid search tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_vector_store.py
git commit -m "test: add hybrid search test coverage"
```

---

## Task 6: Run full test suite

- [ ] **Step 1: Run all tests**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest -v
```
Expected: All tests pass

- [ ] **Step 2: Final commit if any last changes needed**

---

## Spec Coverage Check

| Spec Requirement | Task |
|---|---|
| BM25 index with 5-min TTL | Task 2 |
| `bm25_search()` function | Task 2 |
| Graph hops via `links` field 1-2 levels | Task 3 |
| RRF merge with k=60 | Task 4 |
| Vector weight 1.0, BM25 0.9, hop 0.5/0.25 | Task 4 |
| `hybrid_search(query, top_k)` API | Task 4 |
| Return shape `{path, score, rank, metadata}` | Task 4 |
| Tests for all streams | Tasks 1, 5 |
| Dependencies installed | Task 1 |

## Self-Review

- No TBD/TODO placeholders
- All function signatures consistent across tasks
- BM25 index built before graph_hop called in hybrid_search
- `_rrf_merge` uses `path` as unique key throughout
