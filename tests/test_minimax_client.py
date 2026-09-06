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
    # New fields default to empty when not present in LLM response
    assert result["entities"] == []
    assert result["figure_captions"] == []
    assert result["why_saved_hint"] == ""

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


def test_enrich_handles_unexpected_response_shape(monkeypatch):
    """Malformed or unexpected MiniMax response shapes must not silently pass."""
    from core.minimax_client import enrich

    def mock_post(url, headers, json, timeout):
        class FakeResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {
                    "choices": [{
                        "message": {
                            "content": '{"title": "Test", "type": "article", "tags": [], "summary": "ok", "key_facts": [], "cross_links": [], "entities": [], "figure_captions": [], "why_saved_hint": "", "chapters": [], "key_quotes": [], "topics_covered": []}'
                        }
                    }]
                }
        return FakeResp()

    monkeypatch.setattr("core.minimax_client.MINIMAX_API_KEY", "test-key")
    monkeypatch.setattr("requests.post", mock_post)
    result = enrich("raw text", [], "http://example.com")
    assert result.get("title") == "Test"
    assert result.get("error") is False


def test_enrich_api_error_returns_fallback(monkeypatch):
    """MiniMax API error (non-zero status) must return fallback note with error=True."""
    from core.minimax_client import enrich

    def mock_post(url, headers, json, timeout):
        class FakeResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {
                    "base_resp": {"status_code": 10001, "status_msg": "rate limited"},
                    "choices": []
                }
        return FakeResp()

    monkeypatch.setattr("requests.post", mock_post)
    result = enrich("raw text", [], "http://example.com")
    assert result.get("title") == "Untitled"
    assert result.get("error") is True


def test_enrich_json_decode_error_returns_fallback(monkeypatch):
    """Invalid JSON in MiniMax response must return fallback note, not crash."""
    from core.minimax_client import enrich

    def mock_post(url, headers, json, timeout):
        class FakeResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {
                    "base_resp": {"status_code": 0},
                    "choices": [{"message": {"content": "NOT VALID JSON"}}]
                }
        return FakeResp()

    monkeypatch.setattr("requests.post", mock_post)
    result = enrich("raw text", [], "http://example.com")
    assert result.get("title") == "Untitled"
    assert result.get("error") is True


def test_video_synthesis_preserves_raw_text(monkeypatch):
    """Single-chunk video synthesis must preserve raw_text in returned note."""
    from core.minimax_client import enrich_video_synthesis

    def mock_post(url, headers, json, timeout):
        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {
                    "base_resp": {"status_code": 0},
                    "choices": [{"message": {"content": '{"title":"T","type":"video","tags":[],"summary":"S","key_facts":[],"cross_links":[],"entities":[],"chapters":[],"key_quotes":[],"topics_covered":[],"why_saved_hint":""}'}}]
                }
        return FakeResp()

    monkeypatch.setattr("requests.post", mock_post)

    # Single chunk with raw_text
    chunk_results = [{
        "title": "Chunk 1",
        "summary": "S1",
        "raw_text": "This is the original transcript text that must be preserved",
        "chapters": [], "key_quotes": [], "entities": [],
        "key_facts": [], "topics_covered": [], "tags": [],
        "cross_links": [], "why_saved_hint": "",
    }]
    result = enrich_video_synthesis(chunk_results, "https://youtube.com/watch?v=xxx", [])

    assert "raw_text" in result, "raw_text missing from single-chunk synthesis result"
    assert "original transcript" in result["raw_text"]
