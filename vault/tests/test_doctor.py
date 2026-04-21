# vault/tests/test_doctor.py
"""
Tests for vault/doctor.py — vault junk detection and cleanup.
"""
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# _is_junk_note tests
# ---------------------------------------------------------------------------

class TestIsJunkNoteVideoNoContent:
    """video-no-content: type: video AND raw_text < 50 chars"""

    def test_video_empty_raw_text_is_junk(self):
        from vault.doctor import _is_junk_note
        note = {"type": "video", "raw_text": "", "title": "Test Video"}
        is_junk, reason = _is_junk_note(note, [], "test-video")
        assert is_junk is True
        assert reason == "video-no-content"

    def test_video_short_raw_text_is_junk(self):
        from vault.doctor import _is_junk_note
        note = {"type": "video", "raw_text": "short", "title": "Test"}
        is_junk, reason = _is_junk_note(note, [], "test-video")
        assert is_junk is True
        assert reason == "video-no-content"

    def test_video_substantial_raw_text_is_not_junk(self):
        from vault.doctor import _is_junk_note
        # Video with valid H1 and 300+ raw_text should not be junk (above video threshold and sparse threshold)
        note = {"type": "video", "raw_text": "# Good Video\n\n" + "x" * 290, "title": "Good Video"}
        is_junk, reason = _is_junk_note(note, [], "test-video")
        assert is_junk is False
        assert reason == ""


class TestIsJunkNoteUntitled:
    """Untitled detection."""

    def test_untitled_exact_title_is_junk(self):
        from vault.doctor import _is_junk_note
        note = {"type": "article", "raw_text": "# untitled\n\nSome content", "title": "untitled"}
        is_junk, reason = _is_junk_note(note, [], "untitled")
        assert is_junk is True
        assert reason == "untitled-exact"

    def test_untitled_h1_is_junk(self):
        from vault.doctor import _is_junk_note
        note = {"type": "article", "raw_text": "# untitled\n\nSome content", "title": "Something"}
        is_junk, reason = _is_junk_note(note, [], "something")
        assert is_junk is True
        assert reason == "untitled-h1"

    def test_untitled_uppercase_h1_is_junk(self):
        from vault.doctor import _is_junk_note
        note = {"type": "article", "raw_text": "# UNTITLED\n\nContent", "title": "Something"}
        is_junk, reason = _is_junk_note(note, [], "something")
        assert is_junk is True
        assert reason == "untitled-h1"

    def test_no_h1_is_junk(self):
        from vault.doctor import _is_junk_note
        note = {"type": "article", "raw_text": "Just some text without a heading", "title": "My Note"}
        is_junk, reason = _is_junk_note(note, [], "my-note")
        assert is_junk is True
        assert reason == "untitled-no-h1"

    def test_valid_h1_is_not_junk_for_untitled_check(self):
        from vault.doctor import _is_junk_note
        note = {"type": "article", "raw_text": "# Valid Title\n\n" + "Content here that is definitely more than 200 characters to avoid the sparse check" * 3, "title": "Valid Title"}
        is_junk, reason = _is_junk_note(note, [], "valid-title")
        assert is_junk is False


class TestIsJunkNoteTranscriptFailed:
    """Transcript failed marker detection."""

    def test_no_transcript_marker_is_junk(self):
        from vault.doctor import _is_junk_note
        note = {"type": "video", "raw_text": "# Video [NO_TRANSCRIPT]\n\n" + "x" * 100, "title": "Video [NO_TRANSCRIPT]"}
        is_junk, reason = _is_junk_note(note, [], "video-no-transcript")
        assert is_junk is True
        assert reason == "transcript-failed"

    def test_translation_failed_marker_is_junk(self):
        from vault.doctor import _is_junk_note
        note = {"type": "article", "raw_text": "# Article [TRANSLATION_FAILED]\n\n" + "x" * 100, "title": "Article [TRANSLATION_FAILED]"}
        is_junk, reason = _is_junk_note(note, [], "article-translation-failed")
        assert is_junk is True
        assert reason == "transcript-failed"

    def test_no_transcript_in_body_not_title_is_not_junk(self):
        from vault.doctor import _is_junk_note
        note = {"type": "article", "raw_text": "# Real Title\n\n" + "[NO_TRANSCRIPT] appears in body only and this is enough content to not be sparse " * 5, "title": "Real Title"}
        assert len(note["raw_text"]) > 200
        is_junk, reason = _is_junk_note(note, [], "real-title")
        assert is_junk is False


class TestIsJunkNoteNoBody:
    """No body content detection."""

    def test_empty_body_is_junk(self):
        from vault.doctor import _is_junk_note
        note = {"type": "article", "raw_text": "", "title": "Empty Body", "body": ""}
        is_junk, reason = _is_junk_note(note, [], "empty-body")
        assert is_junk is True
        assert reason == "no-body"

    def test_whitespace_only_body_is_junk(self):
        from vault.doctor import _is_junk_note
        note = {"type": "article", "raw_text": "", "title": "Whitespace Body", "body": "   \n\t  "}
        is_junk, reason = _is_junk_note(note, [], "whitespace-body")
        assert is_junk is True
        assert reason == "no-body"


class TestIsJunkNoteSparse:
    """Sparse content detection."""

    def test_sparse_raw_text_is_junk(self):
        from vault.doctor import _is_junk_note
        note = {"type": "article", "raw_text": "# Sparse\n\nshort", "title": "Sparse Note"}
        is_junk, reason = _is_junk_note(note, [], "sparse-note")
        assert is_junk is True
        assert reason == "sparse"

    def test_substantial_content_is_not_sparse(self):
        from vault.doctor import _is_junk_note
        note = {"type": "article", "raw_text": "# Substantial\n\n" + "x" * 290, "title": "Substantial"}
        is_junk, reason = _is_junk_note(note, [], "substantial")
        assert is_junk is False


class TestIsJunkNoteOrphanedDiscovery:
    """Orphaned discovery note detection."""

    def test_orphaned_discovery_not_in_active_keywords_is_junk(self):
        from vault.doctor import _is_junk_note
        # Body has no wikilink to any active keyword -> orphaned-discovery-no-keyword-link
        body = "# Old Topic\n\n" + ("Content about old topics but nothing linked to active keywords " * 5)
        note = {
            "type": "article",
            "raw_text": body,
            "title": "Old Topic Note",
            "discovery": "auto",
            "source_keyword": "deprecated-keyword",
        }
        active_keywords = ["active-keyword", "another-active"]
        assert len(body) > 200, f"body too short: {len(body)}"
        is_junk, reason = _is_junk_note(note, active_keywords, "old-topic-note")
        assert is_junk is True
        assert reason == "orphaned-discovery-no-keyword-link"

    def test_orphaned_discovery_in_active_keywords_is_not_junk(self):
        from vault.doctor import _is_junk_note
        note = {
            "type": "article",
            "raw_text": "# Active Topic\n\n" + ("Content that is definitely longer than 200 characters here " * 5),
            "title": "Active Topic Note",
            "discovery": "auto",
            "source_keyword": "active-keyword",
        }
        active_keywords = ["active-keyword", "another-active"]
        assert len(note["raw_text"]) > 200
        is_junk, reason = _is_junk_note(note, active_keywords, "active-topic-note")
        assert is_junk is False

    def test_orphaned_discovery_no_wikilink_is_junk(self):
        from vault.doctor import _is_junk_note
        note = {
            "type": "article",
            "raw_text": "# Note Without Link\n\n" + "This content mentions nothing linked to active keywords at all" * 3,
            "title": "Orphan Note",
            "discovery": "auto",
            "source_keyword": "orphaned-keyword",
        }
        active_keywords = ["distributed-systems", "compilers"]
        is_junk, reason = _is_junk_note(note, active_keywords, "orphan-note")
        assert is_junk is True
        assert reason == "orphaned-discovery-no-keyword-link"

    def test_orphaned_discovery_with_wikilink_is_not_junk(self):
        from vault.doctor import _is_junk_note
        note = {
            "type": "article",
            "raw_text": "# Note With Link\n\n" + ("This mentions [[distributed-systems]] in the content here " * 5),
            "title": "Linked Note",
            "discovery": "auto",
            "source_keyword": "orphaned-keyword",
        }
        active_keywords = ["distributed-systems", "compilers"]
        assert len(note["raw_text"]) > 200
        is_junk, reason = _is_junk_note(note, active_keywords, "linked-note")
        assert is_junk is False


# ---------------------------------------------------------------------------
# run_vault_doctor tests
# ---------------------------------------------------------------------------

class TestRunVaultDoctor:
    """Integration tests for run_vault_doctor with real temp vault."""

    def test_run_vault_doctor_returns_categorized_results(self, tmp_path, monkeypatch):
        import vault.doctor
        original_notes_dir = vault.doctor.NOTES_DIR
        vault.doctor.NOTES_DIR = tmp_path

        mock_store = MagicMock()
        with patch("core.vector_store.get_store", return_value=mock_store):
            (tmp_path / "untitled.md").write_text("---\ntitle: untitled\n---\n\n# untitled\n\nNo heading here")
            (tmp_path / "sparse.md").write_text("---\ntitle: Sparse\n---\n\n# Sparse\n\nx")
            (tmp_path / "good.md").write_text("---\ntitle: Good Note\n---\n\n# Good Note\n\n" + "x" * 300)

            result = vault.doctor.run_vault_doctor(["active-keyword"])

        vault.doctor.NOTES_DIR = original_notes_dir

        assert "untitled" in result
        assert "sparse" in result
        assert "deleted" in result
        assert "untitled.md" in [Path(p).name for p in result["untitled"]]
        assert "sparse.md" in [Path(p).name for p in result["sparse"]]

    def test_junk_files_are_deleted(self, tmp_path, monkeypatch):
        import vault.doctor
        original_notes_dir = vault.doctor.NOTES_DIR
        vault.doctor.NOTES_DIR = tmp_path

        mock_store = MagicMock()
        junk_path = tmp_path / "untitled.md"
        junk_path.write_text("---\ntitle: untitled\n---\n\n# untitled\n\nNo heading")

        with patch("core.vector_store.get_store", return_value=mock_store):
            result = vault.doctor.run_vault_doctor([])

        vault.doctor.NOTES_DIR = original_notes_dir

        assert not junk_path.exists(), "Junk file should be deleted"
        assert any("untitled" in p for p in result["deleted"])


# ---------------------------------------------------------------------------
# cleanup_junk legacy wrapper tests
# ---------------------------------------------------------------------------

class TestCleanupJunkLegacyWrapper:
    """cleanup_junk() should delegate to run_vault_doctor([])["deleted"]."""

    def test_cleanup_junk_returns_list_of_deleted(self, tmp_path, monkeypatch):
        import vault.doctor
        original_notes_dir = vault.doctor.NOTES_DIR
        vault.doctor.NOTES_DIR = tmp_path

        mock_store = MagicMock()

        # Create a junk video note with no transcript
        (tmp_path / "bad-video.md").write_text("---\ntitle: Video [NO_TRANSCRIPT]\ntype: video\n---\n\n# Video\n\n")
        # Create a good note
        (tmp_path / "good.md").write_text("---\ntitle: Good\n---\n\n# Good\n\n" + "x" * 300)

        with patch("core.vector_store.get_store", return_value=mock_store):
            deleted = vault.doctor.cleanup_junk()

        vault.doctor.NOTES_DIR = original_notes_dir

        assert isinstance(deleted, list)
        assert any("bad-video" in p for p in deleted)
        assert not (tmp_path / "bad-video.md").exists()
        assert (tmp_path / "good.md").exists()
