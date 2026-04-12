import os
import pytest
from unittest.mock import patch, MagicMock
from contextlib import contextmanager
from ingesters import Document


SAMPLE_VTT = """\
WEBVTT

00:00:01.000 --> 00:00:04.000
The key insight here is continual learning.

00:00:04.000 --> 00:00:07.000
The key insight here is continual learning.

00:00:07.000 --> 00:00:10.000
Agents must update their knowledge over time.
"""


def test_parse_vtt_strips_timestamps():
    from ingesters.youtube import _parse_vtt
    result = _parse_vtt(SAMPLE_VTT)
    assert "-->" not in result
    assert "WEBVTT" not in result


def test_parse_vtt_deduplicates_repeated_lines():
    from ingesters.youtube import _parse_vtt
    result = _parse_vtt(SAMPLE_VTT)
    # "The key insight" appears twice in the VTT but once after dedup
    assert result.count("key insight") == 1


def test_parse_vtt_preserves_content():
    from ingesters.youtube import _parse_vtt
    result = _parse_vtt(SAMPLE_VTT)
    assert "continual learning" in result
    assert "Agents must update" in result


def test_extract_youtube_returns_transcript(tmp_path, monkeypatch):
    from ingesters.youtube import extract_youtube

    vtt_file = tmp_path / "abc123.en.vtt"
    vtt_file.write_text(SAMPLE_VTT)

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: MagicMock(returncode=0))

    @contextmanager
    def mock_tmpdir():
        yield str(tmp_path)

    import ingesters.youtube as yt_module
    monkeypatch.setattr(yt_module.tempfile, "TemporaryDirectory", lambda: mock_tmpdir())

    doc = extract_youtube("https://youtube.com/watch?v=abc123")
    assert isinstance(doc, Document)
    assert doc.content_type == "video"
    assert "continual learning" in doc.raw_text


def test_extract_youtube_no_subtitles_returns_stub(tmp_path, monkeypatch):
    from ingesters.youtube import extract_youtube

    # tmp_path is empty — no .vtt file produced
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: MagicMock(returncode=0))

    @contextmanager
    def mock_tmpdir():
        yield str(tmp_path)

    import ingesters.youtube as yt_module
    monkeypatch.setattr(yt_module.tempfile, "TemporaryDirectory", lambda: mock_tmpdir())

    doc = extract_youtube("https://youtube.com/watch?v=nosubs")
    assert doc.raw_text.startswith("[NO_TRANSCRIPT]")
    assert doc.content_type == "video"
