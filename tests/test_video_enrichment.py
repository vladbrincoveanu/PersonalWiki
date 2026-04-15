import pytest
from unittest.mock import patch, MagicMock


def test_enrich_includes_video_fields():
    from core.minimax_client import enrich

    video_transcript = "Chapter 1: Introduction. " * 100 + "Chapter 2: Core concepts. " * 100

    mock_response = {
        "choices": [{
            "message": {
                "content": '{"title": "Transformers Explained", "type": "video", '
                           '"tags": ["ai", "nlp"], "summary": "Overview of transformers.", '
                           '"key_facts": ["Uses attention"], "cross_links": [], '
                           '"entities": [], "figure_captions": [], '
                           '"why_saved_hint": "Great tutorial", '
                           '"chapters": [{"time": "00:00", "title": "Introduction"}, {"time": "01:00", "title": "Core Concepts"}], '
                           '"key_quotes": [{"text": "Attention is all you need", "speaker": "Vaswani"}], '
                           '"topics_covered": ["self-attention", "transformers", "attention"]}'
            }
        }]
    }

    with patch("core.minimax_client.MINIMAX_API_KEY", "fake"):
        with patch("requests.post", return_value=MagicMock(
            json=lambda: mock_response, raise_for_status=lambda: None
        )):
            result = enrich(video_transcript, [], "https://youtube.com/watch?v=xxx")
            assert "chapters" in result
            assert result["chapters"][0]["title"] == "Introduction"
            assert "key_quotes" in result
            assert "topics_covered" in result
