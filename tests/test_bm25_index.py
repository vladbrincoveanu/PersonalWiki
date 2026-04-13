import pytest
import sys
import os
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
