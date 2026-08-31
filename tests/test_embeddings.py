import pytest

from core.embeddings import embed

pytestmark = pytest.mark.slow


def test_embed_returns_list_of_floats():
    result = embed("PagedAttention uses virtual memory for KV cache.")
    assert isinstance(result, list)
    assert len(result) == 384
    assert all(isinstance(v, float) for v in result)


def test_embed_different_texts_differ():
    v1 = embed("neural network inference optimization")
    v2 = embed("cooking pasta carbonara recipe")
    assert v1 != v2


def test_embed_similar_texts_are_close():
    import math

    v1 = embed("LLM memory management")
    v2 = embed("large language model memory")
    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    cosine = dot / (mag1 * mag2)
    assert cosine > 0.7
