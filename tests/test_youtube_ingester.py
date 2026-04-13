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


def test_extract_youtube_tiered_subtitle_fallback(monkeypatch, tmp_path):
    """Tier 1 (en) fails, tier 2 (en.*) returns transcript."""
    import ingesters.youtube as yt

    # Write VTT file that tier 2 will find
    vtt_file = tmp_path / "video.en.vtt"
    vtt_file.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:05.000\nHello world transcript")

    # Track which tier is being attempted
    tier_attempted = []

    def mock_listdir(d):
        tier_attempted.append(d)
        # Return the vtt file so _run_yt_dlp finds it
        return ["video.en.vtt"]

    monkeypatch.setattr("os.listdir", mock_listdir)

    # Tier 1 (en) — no vtt file, Tier 2 (en.*) — finds the vtt file
    result = yt._try_subtitle_tiers("https://youtube.com/watch?v=abc123AB", str(tmp_path))
    assert result is not None  # tier 2 succeeded
    assert "Hello world transcript" in result


def test_extract_youtube_all_tiers_fail_then_transcript_api(monkeypatch, tmp_path):
    """All yt-dlp tiers fail, transcript API returns transcript."""
    import ingesters.youtube as yt

    api_calls = []
    def mock_transcript_api(video_id):
        api_calls.append(video_id)
        return "API transcript text here"

    # Mock _run_yt_dlp to always return None (no VTT files)
    monkeypatch.setattr("ingesters.youtube._run_yt_dlp", lambda *a, **kw: None)
    monkeypatch.setattr("ingesters.youtube._fetch_transcript_api", mock_transcript_api)

    # Use 11-char video ID so _extract_video_id matches
    doc = yt.extract_youtube("https://youtube.com/watch?v=abc123DEF12")
    assert "API transcript text" in doc.raw_text
    assert api_calls == ["abc123DEF12"]


def test_extract_youtube_returns_stub_when_all_fail(monkeypatch):
    """All tiers and API fail → return NO_TRANSCRIPT stub."""
    import ingesters.youtube as yt

    monkeypatch.setattr("ingesters.youtube._run_yt_dlp", lambda *a, **kw: None)
    monkeypatch.setattr("ingesters.youtube._fetch_transcript_api", lambda vid: None)

    doc = yt.extract_youtube("https://youtube.com/watch?v=abc")
    assert doc.raw_text.startswith("[NO_TRANSCRIPT]")
    assert doc.content_type == "video"
