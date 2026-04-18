import pytest
from pathlib import Path
from unittest.mock import patch

def test_write_note_is_discovery_routes_to_discovered_folder(tmp_path):
    """Discovered notes go to notes/discovered/."""
    from vault.writer import write_note

    notes_dir = tmp_path / "notes"
    discovered_dir = tmp_path / "notes" / "discovered"
    with (
        patch("vault.writer.NOTES_DIR", notes_dir),
        patch("vault.writer.VAULT_PATH", tmp_path),
    ):
        notes_dir.mkdir(parents=True, exist_ok=True)
        discovered_dir.mkdir(parents=True, exist_ok=True)

        path = write_note(
            {"title": "Test Discovery Note", "type": "article", "summary": "A test note.", "key_facts": [], "raw_text": "Full content here."},
            source="https://example.com/test",
            is_discovery=True,
        )

        assert "discovered" in path
        assert Path(path).exists()


def test_write_note_is_discovery_adds_frontmatter(tmp_path):
    """Discovered notes have discovery: auto in frontmatter."""
    from vault.writer import write_note
    import frontmatter

    notes_dir = tmp_path / "notes"
    discovered_dir = tmp_path / "notes" / "discovered"
    with (
        patch("vault.writer.NOTES_DIR", notes_dir),
        patch("vault.writer.VAULT_PATH", tmp_path),
    ):
        notes_dir.mkdir(parents=True, exist_ok=True)
        discovered_dir.mkdir(parents=True, exist_ok=True)

        path = write_note(
            {"title": "Test Discovery Note", "type": "article", "summary": "A test note.", "key_facts": [], "raw_text": "Full content here."},
            source="https://example.com/test",
            is_discovery=True,
        )

        post = frontmatter.load(path)
        assert post.metadata.get("discovery") == "auto"


def test_write_note_is_discovery_false_unchanged(tmp_path):
    """Manual notes (is_discovery=False) are unchanged."""
    from vault.writer import write_note
    import frontmatter

    notes_dir = tmp_path / "notes"
    with (
        patch("vault.writer.NOTES_DIR", notes_dir),
        patch("vault.writer.VAULT_PATH", tmp_path),
    ):
        notes_dir.mkdir(parents=True, exist_ok=True)

        path = write_note(
            {"title": "Manual Note", "type": "article", "summary": "A manual note.", "key_facts": [], "raw_text": "Full content here."},
            source="https://example.com/manual",
            is_discovery=False,
        )

        post = frontmatter.load(path)
        assert "discovery" not in post.metadata
        assert "discovered" not in path