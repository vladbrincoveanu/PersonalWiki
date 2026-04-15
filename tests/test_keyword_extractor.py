import pytest
from unittest.mock import patch, MagicMock


def test_extracts_keywords_from_note():
    from core.keyword_extractor import extract_keywords_from_note

    with patch("core.keyword_extractor.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            json=lambda: {
                "choices": [{
                    "message": {
                        "content": '["reinforcement-learning", "transformers", "attention"]'
                    }
                }]
            },
            raise_for_status=lambda: None
        )
        result = extract_keywords_from_note("RL Paper", "Some longer content that is definitely over 100 characters. " * 5)
        assert result == ["reinforcement-learning", "transformers", "attention"]


def test_returns_empty_when_no_api_key():
    from core.keyword_extractor import extract_keywords_from_note
    with patch("core.keyword_extractor.MINIMAX_API_KEY", ""):
        result = extract_keywords_from_note("Title", "Some content.")
        assert result == []


def test_returns_empty_for_short_content():
    from core.keyword_extractor import extract_keywords_from_note
    with patch("core.keyword_extractor.MINIMAX_API_KEY", "fake"):
        result = extract_keywords_from_note("Title", "Too short")
        assert result == []


def test_handles_malformed_json():
    from core.keyword_extractor import extract_keywords_from_note
    with patch("core.keyword_extractor.MINIMAX_API_KEY", "fake"):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                json=lambda: {"choices": [{"message": {"content": "not json"}}]},
                raise_for_status=lambda: None
            )
            result = extract_keywords_from_note("Title", "Some longer content that is definitely over 100 characters. " * 5)
            assert result == []
