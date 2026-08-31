import pytest
from unittest.mock import patch, MagicMock


pytestmark = pytest.mark.slow


def test_reranker_boosts_relevant_results():
    from core.reranker import CrossEncoderReranker
    reranker = CrossEncoderReranker()

    results = [
        {"path": "notes/rl.md", "text": "Reinforcement learning overview"},
        {"path": "notes/transformers.md", "text": "Transformer architecture for NLP"},
        {"path": "notes/rl_intro.md", "text": "Introduction to RL: Q-learning, policy gradients"},
    ]
    query = "reinforcement learning"

    reranked = reranker.rerank(query, results, top_k=2)

    paths = [r["path"] for r in reranked]
    assert "notes/rl.md" in paths[0] or "notes/rl_intro.md" in paths[0]
    assert "notes/transformers.md" not in paths  # not in top 2 for RL query


def test_reranker_returns_correct_count():
    from core.reranker import CrossEncoderReranker
    reranker = CrossEncoderReranker()
    results = [{"path": f"notes/{i}.md", "text": f"doc {i}"} for i in range(10)]
    reranked = reranker.rerank("query", results, top_k=5)
    assert len(reranked) == 5


def test_reranker_fallback_when_model_unavailable():
    from core.reranker import CrossEncoderReranker
    reranker = CrossEncoderReranker()
    reranker._model = None  # simulate model unavailable
    results = [{"path": f"notes/{i}.md", "text": f"doc {i}"} for i in range(5)]
    reranked = reranker.rerank("query", results, top_k=3)
    assert len(reranked) == 3  # returns results as-is


def test_reranker_adds_rerank_score():
    from core.reranker import CrossEncoderReranker
    reranker = CrossEncoderReranker()
    results = [{"path": "notes/a.md", "text": "test content"}]
    # Mock the _model instance variable directly
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.95]
    reranker._model = mock_model
    reranked = reranker.rerank("test query", results)
    assert "rerank_score" in reranked[0]
    assert reranked[0]["rerank_score"] == 0.95
