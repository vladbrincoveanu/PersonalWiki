import json
from unittest.mock import patch, MagicMock
from core.minimax_client import enrich, _build_prompt

def test_build_prompt_includes_raw_text():
    prompt = _build_prompt(
        raw_text="PagedAttention manages KV cache in blocks.",
        similar_titles=["vllm-serving", "kv-cache-basics"],
        source="https://arxiv.org/abs/2309.06180",
    )
    assert "PagedAttention manages KV cache in blocks." in prompt
    assert "vllm-serving" in prompt
    assert "kv-cache-basics" in prompt

def test_enrich_returns_structured_note():
    mock_response = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "title": "PagedAttention Paper",
                    "type": "paper",
                    "tags": ["llm", "memory"],
                    "summary": "Efficient KV cache management.",
                    "key_facts": ["Uses paged memory", "Reduces fragmentation"],
                    "cross_links": ["vllm-serving"],
                })
            }
        }]
    }
    with patch("core.minimax_client.MINIMAX_API_KEY", "test-key"), \
         patch("core.minimax_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
        )
        result = enrich(
            raw_text="PagedAttention manages KV cache in blocks.",
            similar_titles=["vllm-serving"],
            source="https://arxiv.org/abs/2309.06180",
        )
    assert result["title"] == "PagedAttention Paper"
    assert result["type"] == "paper"
    assert "llm" in result["tags"]
    assert "Efficient KV cache management." in result["summary"]
    assert "vllm-serving" in result["cross_links"]

def test_enrich_fallback_on_api_error():
    with patch("core.minimax_client.requests.post") as mock_post:
        mock_post.side_effect = Exception("connection refused")
        result = enrich(
            raw_text="Some content about neural networks.",
            similar_titles=[],
            source="https://example.com",
        )
    assert result["title"] == "Untitled"
    assert "Some content about neural networks." in result["raw_text"]
    assert result["error"] is True
