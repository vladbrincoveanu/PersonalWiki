import pytest
from unittest.mock import patch, MagicMock


def test_hybrid_search_calls_reranker():
    """hybrid_search should call reranker after RRF merge."""
    from core.vector_store import VectorStore, _rrf_merge

    with patch("core.embeddings.embed") as mock_embed:
        mock_embed.return_value = [0.1] * 384
        with patch("core.bm25_index.bm25_search") as mock_bm25:
            mock_bm25.return_value = []
            with patch.object(VectorStore, "_graph_hop", return_value=[]):
                vs = VectorStore.__new__(VectorStore)  # skip __init__
                vs._db = None
                vs._table = MagicMock()

                # Mock search to return two results with text
                mock_rows = [
                    {"path": "https://example.com/1", "text": "Reinforcement learning...", "score": 0.9, "metadata": {}},
                    {"path": "https://example.com/2", "text": "Transformers are...", "score": 0.7, "metadata": {}},
                ]
                vs._table.search.return_value.limit.return_value.to_list.return_value = mock_rows

                with patch("core.reranker.CrossEncoderReranker") as MockReranker:
                    mock_instance = MagicMock()
                    mock_instance.rerank.return_value = [
                        {"path": "https://example.com/1", "text": "Reinforcement learning...", "rerank_score": 0.95, "metadata": {}},
                        {"path": "https://example.com/2", "text": "Transformers are...", "rerank_score": 0.3, "metadata": {}},
                    ]
                    MockReranker.return_value = mock_instance

                    results = vs.hybrid_search("reinforcement learning", top_k=2)

                    mock_instance.rerank.assert_called_once()
                    assert len(results) == 2
                    assert results[0].get("rerank_score") == 0.95