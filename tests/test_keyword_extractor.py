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


def test_extract_and_classify_all_existing(tmp_path):
    from core.keyword_extractor import extract_and_classify, extract_keywords_from_note
    kws_file = tmp_path / "_keywords"
    kws_file.write_text("python\nmachine-learning\napi\n")
    text = "Python is a programming language. Machine learning uses Python APIs."
    with patch("core.keyword_extractor.extract_keywords_from_note") as mock:
        mock.return_value = ["python", "machine-learning"]
        result = extract_and_classify(text, "Test", kws_file)
    assert result == {"existing": ["python", "machine-learning"], "new": []}


def test_extract_and_classify_some_new(tmp_path):
    from core.keyword_extractor import extract_and_classify
    kws_file = tmp_path / "_keywords"
    kws_file.write_text("python\n")
    text = "Python is great for deep learning and neural networks."
    with patch("core.keyword_extractor.extract_keywords_from_note") as mock:
        mock.return_value = ["python", "deep-learning", "neural-networks"]
        result = extract_and_classify(text, "Test", kws_file)
    assert result["existing"] == ["python"]
    assert "deep-learning" in result["new"]
    assert "neural-networks" in result["new"]


def test_extract_and_classify_empty_text(tmp_path):
    from core.keyword_extractor import extract_and_classify
    kws_file = tmp_path / "_keywords"
    kws_file.write_text("python\n")
    with patch("core.keyword_extractor.extract_keywords_from_note") as mock:
        mock.return_value = []
        result = extract_and_classify("", "Empty", kws_file)
    assert result == {"existing": [], "new": []}


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
