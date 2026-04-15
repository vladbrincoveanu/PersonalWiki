# tests/test_quality_gate.py
import pytest
from unittest.mock import patch, MagicMock

class TestQualityGate:
    def test_rejects_404_content(self):
        from core.quality_gate import QualityGate
        gate = QualityGate()
        result = gate.check(
            url="https://example.com/page",
            raw_text="[404] Page not found",
            keyword="test"
        )
        assert result.pass_ is False
        assert "404" in result.reason

    def test_rejects_thin_content(self):
        from core.quality_gate import QualityGate
        gate = QualityGate()
        result = gate.check(
            url="https://example.com/page",
            raw_text="Too short",
            keyword="test"
        )
        assert result.pass_ is False
        assert "thin" in result.reason.lower()

    def test_rejects_paywalled_content(self):
        from core.quality_gate import QualityGate
        gate = QualityGate()
        result = gate.check(
            url="https://example.com/page",
            raw_text="[PAYWALLED] Subscribe to read...",
            keyword="test"
        )
        assert result.pass_ is False

    def test_rejects_short_video_transcript(self):
        from core.quality_gate import QualityGate
        gate = QualityGate()
        result = gate.check(
            url="https://youtube.com/watch?v=xxx",
            raw_text="Short transcript",
            keyword="test",
            content_type="video"
        )
        assert result.pass_ is False
        assert "200" in result.reason

    def test_passes_valid_content(self):
        from core.quality_gate import QualityGate
        gate = QualityGate()
        result = gate.check(
            url="https://example.com/good-article",
            raw_text="This is a substantial article with real content that is definitely over five hundred characters long. " * 5,
            keyword="test"
        )
        assert result.pass_ is True