import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from vault.scanner import parse_wikilinks, scan_vault

def test_parse_wikilinks_basic():
    text = "See [[related-note]] and also [[another-note]] for context."
    links = parse_wikilinks(text)
    assert "related-note" in links
    assert "another-note" in links

def test_parse_wikilinks_empty():
    assert parse_wikilinks("No links here.") == []

def test_parse_wikilinks_deduplicates():
    text = "[[note-a]] and [[note-a]] again."
    links = parse_wikilinks(text)
    assert links.count("note-a") == 1

def test_scan_vault_indexes_notes():
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()

        note_content = """---
title: Test Note
type: article
tags: [ai]
source: https://example.com
ingested: 2026-04-10
---

## Summary
Test summary.

See [[related-note]] for more.
"""
        (notes_dir / "test-note.md").write_text(note_content)

        mock_store = MagicMock()
        mock_embed = MagicMock(return_value=[0.1] * 384)

        with patch("vault.scanner.NOTES_DIR", notes_dir), \
             patch("vault.scanner.get_store", return_value=mock_store), \
             patch("vault.scanner.embed", mock_embed):
            count = scan_vault()

    assert count == 1
    mock_store.upsert.assert_called_once()
    call_kwargs = mock_store.upsert.call_args.kwargs
    assert "related-note" in call_kwargs["links"]
    assert call_kwargs["metadata"]["title"] == "Test Note"

def test_scan_vault_incremental_skips_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()

        note_path = notes_dir / "test-note.md"
        note_path.write_text("---\ntitle: T\n---\n\nContent.")

        mock_store = MagicMock()
        mock_store.get_mtime.return_value = note_path.stat().st_mtime + 1  # newer than file

        with patch("vault.scanner.NOTES_DIR", notes_dir), \
             patch("vault.scanner.get_store", return_value=mock_store), \
             patch("vault.scanner.embed", MagicMock(return_value=[0.1] * 384)):
            count = scan_vault()

    assert count == 0  # skipped because index is newer
