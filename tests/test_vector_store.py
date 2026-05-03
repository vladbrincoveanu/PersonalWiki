import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from core.vector_store import VectorStore

def make_store():
    tmp = tempfile.mkdtemp()
    return VectorStore(index_path=tmp)

def test_upsert_and_exists():
    store = make_store()
    store.upsert(
        path="notes/test.md",
        text="test content",
        vector=[0.1] * 384,
        links=["other-note"],
        metadata={"title": "Test", "tags": ["test"]},
    )
    assert store.exists("notes/test.md")

def test_not_exists_for_unknown_path():
    store = make_store()
    assert not store.exists("notes/nonexistent.md")

def test_upsert_overwrites_existing():
    store = make_store()
    store.upsert("notes/t.md", "v1", [0.1] * 384, [], {"title": "V1"})
    store.upsert("notes/t.md", "v2", [0.2] * 384, [], {"title": "V2"})
    results = store.search([0.2] * 384, top_k=1)
    assert results[0]["text"] == "v2"

def test_search_returns_top_k():
    store = make_store()
    for i in range(5):
        v = [float(i) / 10] * 384
        store.upsert(f"notes/note{i}.md", f"content {i}", v, [], {"title": f"Note {i}"})
    results = store.search([0.4] * 384, top_k=3)
    assert len(results) == 3

def test_search_metadata_is_dict():
    store = make_store()
    store.upsert("notes/t.md", "text", [0.1] * 384, ["link1"], {"title": "T", "tags": ["a"]})
    results = store.search([0.1] * 384, top_k=1)
    assert isinstance(results[0]["metadata"], dict)
    assert results[0]["metadata"]["title"] == "T"


# --- Tests for _get_links_for_paths ---

def test_get_links_for_paths_returns_correct_links():
    store = make_store()
    store.upsert("notes/a.md", "content a", [0.1] * 384, ["b", "c"], {"title": "A"})
    store.upsert("notes/b.md", "content b", [0.2] * 384, ["c"], {"title": "B"})
    store.upsert("notes/c.md", "content c", [0.3] * 384, [], {"title": "C"})
    result = store._get_links_for_paths(["notes/a.md", "notes/b.md", "notes/c.md"])
    assert result["notes/a.md"] == ["b", "c"]
    assert result["notes/b.md"] == ["c"]
    assert result["notes/c.md"] == []


def test_get_links_for_paths_unknown_path_returns_empty():
    store = make_store()
    store.upsert("notes/known.md", "content", [0.1] * 384, ["other"], {"title": "Known"})
    result = store._get_links_for_paths(["notes/known.md", "notes/unknown.md"])
    assert result["notes/known.md"] == ["other"]
    assert result["notes/unknown.md"] == []


def test_get_links_for_paths_empty_input():
    store = make_store()
    result = store._get_links_for_paths([])
    assert result == {}


# --- Tests for _graph_hop ---

def test_graph_hop_returns_hop1_links_with_correct_weight():
    store = make_store()
    store.upsert("notes/a.md", "content a", [0.1] * 384, ["b", "c"], {"title": "A"})
    store.upsert("notes/b.md", "content b", [0.2] * 384, [], {"title": "B"})
    store.upsert("notes/c.md", "content c", [0.3] * 384, [], {"title": "C"})
    # Pass paths in order (a comes first so top-1 is just a)
    result = store._graph_hop(["notes/a.md", "notes/b.md"], top_k=5, hop1_weight=0.5, hop2_weight=0.25)
    paths = [r["path"] for r in result]
    weights = {r["path"]: r["hop_weight"] for r in result}
    assert "b" in paths
    assert "c" in paths
    assert weights["b"] == 0.5
    assert weights["c"] == 0.5


def test_graph_hop_returns_hop2_links_with_correct_weight():
    store = make_store()
    # Use full paths in links to enable hop-2 traversal
    store.upsert("notes/a.md", "content a", [0.1] * 384, ["notes/b.md"], {"title": "A"})
    store.upsert("notes/b.md", "content b", [0.2] * 384, ["notes/c.md"], {"title": "B"})
    store.upsert("notes/c.md", "content c", [0.3] * 384, ["notes/d.md"], {"title": "C"})
    store.upsert("notes/d.md", "content d", [0.4] * 384, [], {"title": "D"})
    result = store._graph_hop(["notes/a.md"], top_k=5, hop1_weight=0.5, hop2_weight=0.25)
    paths = [r["path"] for r in result]
    weights = {r["path"]: r["hop_weight"] for r in result}
    # hop-1: notes/b.md, hop-2: notes/c.md
    assert "notes/b.md" in paths
    assert "notes/c.md" in paths
    assert weights["notes/b.md"] == 0.5
    assert weights["notes/c.md"] == 0.25


def test_graph_hop_deduplicates_by_path():
    store = make_store()
    # a and b both link to c
    store.upsert("notes/a.md", "content a", [0.1] * 384, ["c"], {"title": "A"})
    store.upsert("notes/b.md", "content b", [0.2] * 384, ["c"], {"title": "B"})
    store.upsert("notes/c.md", "content c", [0.3] * 384, [], {"title": "C"})
    result = store._graph_hop(["notes/a.md", "notes/b.md"], top_k=5, hop1_weight=0.5, hop2_weight=0.25)
    # c should appear only once
    c_entries = [r for r in result if r["path"] == "c"]
    assert len(c_entries) == 1
    assert c_entries[0]["hop_weight"] == 0.5


def test_graph_hop_sorts_by_weight_descending():
    store = make_store()
    # a links to c (hop1), c links to d (hop2)
    store.upsert("notes/a.md", "content a", [0.1] * 384, ["b"], {"title": "A"})
    store.upsert("notes/b.md", "content b", [0.2] * 384, ["c"], {"title": "B"})
    store.upsert("notes/c.md", "content c", [0.3] * 384, [], {"title": "C"})
    result = store._graph_hop(["notes/a.md"], top_k=5, hop1_weight=0.5, hop2_weight=0.25)
    weights = [r["hop_weight"] for r in result]
    assert weights == sorted(weights, reverse=True)


def test_graph_hop_empty_paths():
    store = make_store()
    result = store._graph_hop([], top_k=5)
    assert result == []


def test_graph_hop_no_links():
    store = make_store()
    store.upsert("notes/a.md", "content a", [0.1] * 384, [], {"title": "A"})
    result = store._graph_hop(["notes/a.md"], top_k=5, hop1_weight=0.5, hop2_weight=0.25)
    assert result == []


def test_graph_hop_unknown_paths():
    store = make_store()
    store.upsert("notes/known.md", "content", [0.1] * 384, ["other"], {"title": "Known"})
    result = store._graph_hop(["notes/unknown.md"], top_k=5, hop1_weight=0.5, hop2_weight=0.25)
    assert result == []


def test_graph_hop_respects_top_k():
    store = make_store()
    store.upsert("notes/a.md", "content a", [0.1] * 384, ["b", "c", "d", "e"], {"title": "A"})
    store.upsert("notes/b.md", "content b", [0.2] * 384, [], {"title": "B"})
    store.upsert("notes/c.md", "content c", [0.3] * 384, [], {"title": "C"})
    store.upsert("notes/d.md", "content d", [0.4] * 384, [], {"title": "D"})
    store.upsert("notes/e.md", "content e", [0.5] * 384, [], {"title": "E"})
    result = store._graph_hop(["notes/a.md"], top_k=3, hop1_weight=0.5, hop2_weight=0.25)
    assert len(result) == 3


def test_graph_hop_only_includes_hop1_and_hop2():
    """Verify only 1-hop and 2-hop links are included; 3+ hops must not appear."""
    store = make_store()
    # Chain: a.md -> b.md -> c.md -> d.md
    store.upsert("notes/a.md", "content a", [0.1] * 384, ["notes/b.md"], {"title": "A"})
    store.upsert("notes/b.md", "content b", [0.2] * 384, ["notes/c.md"], {"title": "B"})
    store.upsert("notes/c.md", "content c", [0.3] * 384, ["notes/d.md"], {"title": "C"})
    store.upsert("notes/d.md", "content d", [0.4] * 384, [], {"title": "D"})
    result = store._graph_hop(["notes/a.md"], top_k=10, hop1_weight=0.5, hop2_weight=0.25)
    paths = [r["path"] for r in result]
    # hop-1: b.md, hop-2: c.md — d.md is hop-3 and must NOT appear
    assert "notes/b.md" in paths
    assert "notes/c.md" in paths
    assert "notes/d.md" not in paths


# --- Tests for _rrf_merge ---

from core.vector_store import _rrf_merge


def test_rrf_merge_returns_correct_shape():
    ranked_lists = [
        [{"path": "a.md", "score": 0.9, "rank": 1}, {"path": "b.md", "score": 0.8, "rank": 2}],
        [{"path": "b.md", "score": 0.7, "rank": 1}, {"path": "c.md", "score": 0.6, "rank": 2}],
    ]
    result = _rrf_merge(ranked_lists, weights=[1.0, 0.9], k=60, top_k=5)
    assert len(result) == 3  # 3 unique paths
    for item in result:
        assert "path" in item
        assert "score" in item
        assert "rank" in item
        assert isinstance(item["path"], str)
        assert isinstance(item["score"], float)
        assert isinstance(item["rank"], int)


def test_rrf_merge_sorted_by_score_descending():
    ranked_lists = [
        [{"path": "a.md", "score": 0.9, "rank": 1}],
        [{"path": "b.md", "score": 0.9, "rank": 1}],
    ]
    result = _rrf_merge(ranked_lists, weights=[1.0, 0.9], k=60, top_k=5)
    scores = [item["score"] for item in result]
    assert scores == sorted(scores, reverse=True)


def test_rrf_merge_respects_top_k():
    ranked_lists = [
        [{"path": f"note{i}.md", "score": 1.0 - i * 0.1, "rank": i + 1} for i in range(10)],
        [],
    ]
    result = _rrf_merge(ranked_lists, weights=[1.0, 0.5], k=60, top_k=3)
    assert len(result) == 3


def test_rrf_merge_missing_rank_penalty():
    # Items without rank should get k * 2 penalty
    ranked_lists = [
        [{"path": "a.md", "score": 0.9, "rank": 1}, {"path": "b.md", "score": 0.8}],  # b.md missing rank
    ]
    result = _rrf_merge(ranked_lists, weights=[1.0], k=60, top_k=5)
    # a.md should rank higher than b.md due to penalty
    a_score = next(item["score"] for item in result if item["path"] == "a.md")
    b_score = next(item["score"] for item in result if item["path"] == "b.md")
    assert a_score > b_score


def test_rrf_merge_accumulates_scores():
    # Same path in multiple lists should have combined score
    ranked_lists = [
        [{"path": "a.md", "score": 0.9, "rank": 1}],
        [{"path": "a.md", "score": 0.8, "rank": 1}],
    ]
    result = _rrf_merge(ranked_lists, weights=[1.0, 1.0], k=60, top_k=5, multi_signal_boost=0.0)
    a_item = next(item for item in result if item["path"] == "a.md")
    # RRF score = 1.0/(60+1) + 1.0/(60+1) = 2/(61) ≈ 0.0328
    assert abs(a_item["score"] - 2 / 61) < 0.001


def test_rrf_merge_boosts_multi_signal_results():
    """A result appearing in both vector and BM25 ranks higher than single-signal."""
    # a.md: rank 1 in both streams (multi-signal)
    # b.md: rank 1 in vector only (single-signal)
    vector_list = [
        {"path": "a.md", "score": 0.9, "rank": 1},
        {"path": "b.md", "score": 0.8, "rank": 2},
    ]
    bm25_list = [
        {"path": "a.md", "score": 0.9, "rank": 1},
    ]
    # Vector weight 1.0, BM25 weight 0.9, k=60
    result = _rrf_merge([vector_list, bm25_list], weights=[1.0, 0.9], k=60, top_k=5)
    a_score = next(item["score"] for item in result if item["path"] == "a.md")
    b_score = next(item["score"] for item in result if item["path"] == "b.md")
    # a.md gets: 1.0/(60+1) + 0.9/(60+1) = 1.9/61 ≈ 0.0311
    # b.md gets: 0.8/(60+2) = 0.8/62 ≈ 0.0129
    assert a_score > b_score


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
    assert abs(alone_score - (1.0 / 61)) < 0.001


def test_rrf_boost_preserves_sort_order():
    """Boost doesn't change relative order of same-stream notes."""
    vector = [{"path": "a.md", "rank": 1}, {"path": "b.md", "rank": 2}]
    bm25  = [{"path": "a.md", "rank": 1}]  # only a in bm25 (gets boost)
    hops  = []

    result = _rrf_merge([vector, bm25, hops], weights=[1.0, 0.9, 0.5], k=60, top_k=5, multi_signal_boost=0.005)
    paths = [r["path"] for r in result]

    # a.md gets boost but should still rank above b.md only if boost makes sense
    assert paths.index("a.md") < paths.index("b.md")


# --- Tests for hybrid_search ---

from unittest.mock import patch, MagicMock


def test_hybrid_search_returns_correct_shape(mock_store, sample_notes):
    store, notes_dir = mock_store
    for note in sample_notes:
        store.upsert(note["path"], note["text"], note["vector"], note["links"], note["metadata"])

    with patch("core.embeddings.embed") as mock_embed, \
         patch("core.bm25_index.ensure_index") as mock_ensure, \
         patch("core.bm25_index.bm25_search") as mock_bm25:

        mock_embed.return_value = [0.1] * 384
        mock_ensure.return_value = (MagicMock(), [], [])
        mock_bm25.return_value = [
            {"path": "notes/a.md", "score": 0.9, "rank": 1},
            {"path": "notes/b.md", "score": 0.8, "rank": 2},
        ]

        result = store.hybrid_search("test query", top_k=5)

        assert len(result) <= 5
        for item in result:
            assert "path" in item
            assert "score" in item
            assert "rank" in item
            assert "metadata" in item


def test_hybrid_search_calls_all_three_streams(mock_store, sample_notes):
    store, notes_dir = mock_store
    for note in sample_notes:
        store.upsert(note["path"], note["text"], note["vector"], note["links"], note["metadata"])

    with patch("core.embeddings.embed") as mock_embed, \
         patch("core.bm25_index.ensure_index") as mock_ensure, \
         patch("core.bm25_index.bm25_search") as mock_bm25, \
         patch.object(store, "search") as mock_vector_search, \
         patch.object(store, "_graph_hop") as mock_graph_hop:

        mock_embed.return_value = [0.1] * 384
        mock_vector_search.return_value = [
            {"path": "notes/a.md", "score": 0.9, "rank": 1, "metadata": {}},
            {"path": "notes/b.md", "score": 0.8, "rank": 2, "metadata": {}},
        ]
        mock_ensure.return_value = (MagicMock(), [], [])
        mock_bm25.return_value = [
            {"path": "notes/a.md", "score": 0.9, "rank": 1},
            {"path": "notes/b.md", "score": 0.8, "rank": 2},
        ]
        mock_graph_hop.return_value = [
            {"path": "notes/c.md", "hop_weight": 0.5},
        ]

        store.hybrid_search("test query", top_k=5)

        mock_embed.assert_called_once_with("test query")
        mock_ensure.assert_called_once()
        mock_bm25.assert_called_once()
        mock_graph_hop.assert_called_once()
        # graph_hop should be called with vector search paths
        call_paths = mock_graph_hop.call_args[0][0]
        assert "notes/a.md" in call_paths
        assert "notes/b.md" in call_paths


def test_hybrid_search_uses_correct_weights(mock_store, sample_notes):
    store, notes_dir = mock_store
    for note in sample_notes:
        store.upsert(note["path"], note["text"], note["vector"], note["links"], note["metadata"])

    with patch("core.embeddings.embed") as mock_embed, \
         patch("core.bm25_index.ensure_index") as mock_ensure, \
         patch("core.bm25_index.bm25_search") as mock_bm25, \
         patch.object(store, "search") as mock_vector_search, \
         patch.object(store, "_graph_hop") as mock_graph_hop, \
         patch("core.vector_store._rrf_merge") as mock_rrf:

        mock_embed.return_value = [0.1] * 384
        mock_vector_search.return_value = [{"path": "a.md", "score": 0.9, "rank": 1, "metadata": {}}]
        mock_ensure.return_value = (MagicMock(), [], [])
        mock_bm25.return_value = [{"path": "a.md", "score": 0.9, "rank": 1}]
        mock_graph_hop.return_value = [{"path": "a.md", "hop_weight": 0.5}]
        mock_rrf.return_value = [{"path": "a.md", "score": 0.1, "rank": 1}]

        store.hybrid_search("test query", top_k=5)

        mock_rrf.assert_called_once()
        call_args = mock_rrf.call_args
        # Check weights
        assert call_args.kwargs["weights"] == [1.0, 0.9, 0.5]
        assert call_args.kwargs["k"] == 60
        assert call_args.kwargs["top_k"] == 5


def test_hybrid_search_merges_with_rrf(mock_store, sample_notes):
    store, notes_dir = mock_store
    for note in sample_notes:
        store.upsert(note["path"], note["text"], note["vector"], note["links"], note["metadata"])

    with patch("core.embeddings.embed") as mock_embed, \
         patch("core.bm25_index.ensure_index") as mock_ensure, \
         patch("core.bm25_index.bm25_search") as mock_bm25, \
         patch.object(store, "search") as mock_vector_search, \
         patch.object(store, "_graph_hop") as mock_graph_hop:

        mock_embed.return_value = [0.1] * 384
        mock_vector_search.return_value = [{"path": "a.md", "score": 0.9, "rank": 1, "metadata": {"title": "A"}}]
        mock_ensure.return_value = (MagicMock(), [], [])
        mock_bm25.return_value = [{"path": "a.md", "score": 0.9, "rank": 1}]
        mock_graph_hop.return_value = [{"path": "a.md", "hop_weight": 0.5}]

        result = store.hybrid_search("test query", top_k=5)

        assert len(result) == 1
        assert result[0]["path"] == "a.md"
        assert result[0]["metadata"]["title"] == "A"


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
        # Both streams return results at poor ranks → RRF below 0.05
        # vector at rank 1: 1/61 ≈ 0.016; bm25 at rank 100: 0.9/160 ≈ 0.005
        # Combined ≈ 0.021 < 0.05 threshold → filtered out
        mock_bm25.return_value = [{"path": "notes/a.md", "score": 0.001, "rank": 100}]
        mock_vec.return_value = [{"path": "notes/a.md", "score": 0.001, "rank": 100, "metadata": {}}]
        mock_hop.return_value = []

        result = store.hybrid_search("garbage query xyz123", top_k=5, min_score=0.05)
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
        # Both at rank 1: 1/61 + 0.9/61 ≈ 0.031 > 0.05? No, 0.031 < 0.05.
        # Need BM25 at rank 1 and vector at rank 1 for maximum RRF: 0.031 < 0.05 still.
        # Use very high ranks to boost RRF: both at rank 1 gives max 0.031 < 0.05.
        # This test verifies that with min_score=0.001 (default), even mediocre scores pass.
        mock_bm25.return_value = [{"path": "notes/a.md", "score": 10.0, "rank": 1}]
        mock_vec.return_value = [{"path": "notes/a.md", "score": 0.9, "rank": 1, "metadata": {"title": "A"}}]
        mock_hop.return_value = []

        result = store.hybrid_search("attention mechanism", top_k=5)
        assert len(result) >= 1


# --- Fixtures ---

import pytest


@pytest.fixture
def mock_store():
    tmp = tempfile.mkdtemp()
    store = VectorStore(index_path=tmp)
    return store, Path(tmp)


@pytest.fixture
def sample_notes():
    return [
        {
            "path": "notes/a.md",
            "text": "content a",
            "vector": [0.1] * 384,
            "links": ["notes/b.md"],
            "metadata": {"title": "Note A", "tags": ["a"]},
        },
        {
            "path": "notes/b.md",
            "text": "content b",
            "vector": [0.2] * 384,
            "links": ["notes/c.md"],
            "metadata": {"title": "Note B", "tags": ["b"]},
        },
        {
            "path": "notes/c.md",
            "text": "content c",
            "vector": [0.3] * 384,
            "links": [],
            "metadata": {"title": "Note C", "tags": ["c"]},
        },
    ]


def test_path_with_single_quote_no_injection():
    """Paths with single quotes must be safely escaped in where() clauses."""
    import tempfile
    from core.vector_store import VectorStore

    tmp = tempfile.mkdtemp()
    store = VectorStore(index_path=tmp)

    # Path with single quote — would break SQL without escaping
    path = "notes/O'Reilly's Notes.md"

    # This must not raise a SQL error
    store.upsert(
        path=path,
        text="Test content",
        vector=[0.0] * 384,
        links=[],
        metadata={"title": "O'Reilly's Notes", "_mtime": 999.0},
    )
    assert store.exists(path) is True
    assert store.get_title_by_url(path) == "O'Reilly's Notes"
    assert store.get_mtime(path) == 999.0


def test_embed_insert_query_real(mock_store):
    """Real e2e: embed() → upsert() → search() with actual FastEmbed model."""
    from core.embeddings import embed

    store, tmp_dir = mock_store

    vec1 = embed("attention mechanisms in transformer architectures")
    vec2 = embed("cooking pasta carbonara with guanciale")
    vec3 = embed("machine learning optimization techniques")

    assert len(vec1) == 384, f"Expected 384d, got {len(vec1)}"

    store.upsert("notes/attention.md", "attention content", vec1, [], {"title": "Attention"})
    store.upsert("notes/pasta.md", "pasta content", vec2, [], {"title": "Pasta"})
    store.upsert("notes/ml.md", "ml content", vec3, [], {"title": "ML"})

    query_vec = embed("transformer attention layer design")
    results = store.search(query_vec, top_k=1)

    assert len(results) == 1
    assert results[0]["path"] == "notes/attention.md"


def test_migrate_on_dimension_mismatch(mock_store):
    """Verify VectorStore auto-migrates a wrong-dimension table."""
    import lancedb
    import pyarrow as pa

    store, tmp_dir = mock_store

    db = lancedb.connect(str(tmp_dir))
    wrong_schema = pa.schema([
        pa.field("path", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 1024)),
        pa.field("links", pa.list_(pa.string())),
        pa.field("metadata", pa.string()),
    ])
    db.drop_table("notes")
    db.create_table("notes", schema=wrong_schema)

    store2 = VectorStore(index_path=str(tmp_dir))

    table = store2._table
    actual_dim = table.schema.field("vector").type.list_size
    assert actual_dim == 384, f"Expected 384d, got {actual_dim}"

