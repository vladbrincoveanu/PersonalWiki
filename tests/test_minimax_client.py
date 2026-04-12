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


def test_enrich_returns_entities_and_figure_captions():
    mock_response = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "title": "Test Paper",
                    "type": "paper",
                    "tags": ["ml"],
                    "summary": "A test summary.",
                    "key_facts": ["Fact one"],
                    "cross_links": [],
                    "entities": [
                        {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"}
                    ],
                    "figure_captions": ["Overview of the model architecture"],
                    "why_saved_hint": "Relevant to my research on X.",
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
            raw_text="Some content <!-- image --> more content.",
            similar_titles=[],
            source="https://example.com/paper.pdf",
        )

    assert result["entities"] == [{"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"}]
    assert result["figure_captions"] == ["Overview of the model architecture"]
    assert result["why_saved_hint"] == "Relevant to my research on X."


def test_enrich_fallback_includes_new_field_defaults():
    with patch("core.minimax_client.requests.post") as mock_post:
        mock_post.side_effect = Exception("connection refused")
        result = enrich(
            raw_text="Some content.",
            similar_titles=[],
            source="https://example.com",
        )

    assert result["entities"] == []
    assert result["figure_captions"] == []
    assert result["why_saved_hint"] == ""


def test_enrich_no_api_key_fallback_includes_new_field_defaults():
    from unittest.mock import patch
    from core.minimax_client import enrich

    with patch("core.minimax_client.MINIMAX_API_KEY", ""):
        result = enrich(raw_text="x", similar_titles=[], source="https://example.com")

    assert result["entities"] == []
    assert result["figure_captions"] == []
    assert result["why_saved_hint"] == ""
