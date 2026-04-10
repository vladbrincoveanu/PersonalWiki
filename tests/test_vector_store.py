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
