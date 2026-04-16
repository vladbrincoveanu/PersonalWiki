# vault/tests/test_junk_cleaner.py
import pytest
import tempfile
import os
from pathlib import Path

def test_cleanup_junk_detects_empty_video_note():
    """Video note with no raw_text should be marked as junk."""
    from vault.junk_cleaner import _is_junk_note
    note = {"type": "video", "raw_text": "", "title": "Test Video"}
    assert _is_junk_note(note) is True

def test_cleanup_junk_detects_short_raw_text():
    """Video note with raw_text < 50 chars should be marked as junk."""
    from vault.junk_cleaner import _is_junk_note
    note = {"type": "video", "raw_text": "short", "title": "Test"}
    assert _is_junk_note(note) is True

def test_cleanup_junk_allows_article_notes():
    """Article notes should never be junk regardless of content."""
    from vault.junk_cleaner import _is_junk_note
    note = {"type": "article", "raw_text": "", "title": "Article"}
    assert _is_junk_note(note) is False

def test_cleanup_junk_allows_video_with_transcript():
    """Video note with substantial raw_text should not be junk."""
    from vault.junk_cleaner import _is_junk_note
    note = {"type": "video", "raw_text": "x" * 100, "title": "Good Video"}
    assert _is_junk_note(note) is False

def test_cleanup_junk_detects_no_transcript_marker():
    """Note title with [NO_TRANSCRIPT] should be junk regardless of type."""
    from vault.junk_cleaner import _is_junk_note
    note = {"type": "video", "raw_text": "x" * 100, "title": "Video [NO_TRANSCRIPT]"}
    assert _is_junk_note(note) is True

def test_cleanup_junk_detects_translation_failed_marker():
    """Note title with [TRANSLATION_FAILED] should be junk."""
    from vault.junk_cleaner import _is_junk_note
    note = {"type": "article", "raw_text": "", "title": "Article [TRANSLATION_FAILED]"}
    assert _is_junk_note(note) is True