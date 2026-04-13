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
