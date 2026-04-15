import pytest
import sys
from unittest.mock import MagicMock


def test_video_priority_scoring(monkeypatch):
    # Stub out youtube_transcript_api before importing ingesters.youtube
    # (the module imports it at the top level)
    stub_module = MagicMock()
    sys.modules["youtube_transcript_api"] = stub_module
    try:
        from ingesters.youtube import score_video_priority

        videos = [
            {"url": "https://youtube.com/watch?v=1", "views": 1000000, "days_old": 30, "topic_match": 0.9},
            {"url": "https://youtube.com/watch?v=2", "views": 50000, "days_old": 7, "topic_match": 0.8},
            {"url": "https://youtube.com/watch?v=3", "views": 10000, "days_old": 3, "topic_match": 0.6},
        ]

        scored = [score_video_priority(v, user_keywords=["transformers", "attention"])
                 for v in videos]

        # Highest score should be the 1M view, 30-day old, high topic match video
        scores = [s["priority_score"] for s in scored]
        assert scores == sorted(scores, reverse=True)
    finally:
        # Clean up so later tests don't get the stub
        del sys.modules["youtube_transcript_api"]
        if "ingesters.youtube" in sys.modules:
            del sys.modules["ingesters.youtube"]


def test_video_gate_rejects_short_transcript():
    from core.quality_gate import QualityGate
    gate = QualityGate()

    result = gate.check(
        url="https://youtube.com/watch?v=xxx",
        raw_text="Short transcript. " * 10,  # ~20 words
        keyword="transformers",
        content_type="video",
    )
    assert result.pass_ is False
    assert "200" in result.reason
