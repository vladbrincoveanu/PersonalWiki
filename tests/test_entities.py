import tempfile
from pathlib import Path
from unittest.mock import patch
import frontmatter
from vault.entities import upsert_entity_notes


def test_upsert_creates_stub_notes():
    entities = [
        {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
        {"name": "ROC Analysis", "slug": "roc-analysis", "type": "concept"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.entities.NOTES_DIR", notes_dir):
            upsert_entity_notes(entities)

        assert (notes_dir / "mimic-iv.md").exists()
        assert (notes_dir / "roc-analysis.md").exists()

        post = frontmatter.load(str(notes_dir / "mimic-iv.md"))
        assert post.metadata["title"] == "MIMIC-IV"
        assert post.metadata["type"] == "dataset"
        assert "_Not filled in yet._" in post.content


def test_upsert_does_not_overwrite_existing_note():
    entities = [{"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"}]
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        existing = notes_dir / "mimic-iv.md"
        existing.write_text("---\ntitle: MIMIC-IV\n---\nMy custom content.")

        with patch("vault.entities.NOTES_DIR", notes_dir):
            upsert_entity_notes(entities)

        assert "My custom content." in existing.read_text()


def test_upsert_skips_entities_with_missing_fields():
    entities = [
        {"name": "", "slug": "empty-name", "type": "concept"},
        {"name": "Valid Entity", "slug": "", "type": "concept"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.entities.NOTES_DIR", notes_dir):
            upsert_entity_notes(entities)

        assert list(notes_dir.iterdir()) == []


def test_upsert_empty_list_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.entities.NOTES_DIR", notes_dir):
            upsert_entity_notes([])

        assert list(notes_dir.iterdir()) == []


def test_upsert_skips_non_dict_entities():
    """LLM may return a malformed list (e.g. strings instead of dicts); must not raise."""
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.entities.NOTES_DIR", notes_dir):
            upsert_entity_notes(["MIMIC-IV", 42, None])

        assert list(notes_dir.iterdir()) == []


def test_upsert_skips_path_traversal_slug():
    entities = [{"name": "Evil", "slug": "../evil", "type": "concept"}]
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.entities.NOTES_DIR", notes_dir):
            upsert_entity_notes(entities)

        # The file must NOT be created outside the notes directory
        assert not (Path(tmp) / "evil.md").exists()
        assert list(notes_dir.iterdir()) == []
