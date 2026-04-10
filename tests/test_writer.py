import tempfile
from pathlib import Path
from unittest.mock import patch
import frontmatter
from vault.writer import write_note, slugify

def test_slugify_basic():
    assert slugify("PagedAttention Paper") == "pagedattention-paper"

def test_slugify_special_chars():
    assert slugify("GPT-4: What's New?") == "gpt-4-whats-new"

def test_slugify_extra_spaces():
    assert slugify("  hello   world  ") == "hello-world"

def test_write_note_creates_file():
    note = {
        "title": "Test Note",
        "type": "article",
        "tags": ["ai", "test"],
        "summary": "A test summary.",
        "key_facts": ["Fact one", "Fact two"],
        "cross_links": ["related-note"],
        "raw_text": "Original raw content.",
        "error": False,
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        assert path.endswith("test-note.md")
        assert Path(path).exists()

def test_write_note_frontmatter_correct():
    note = {
        "title": "Test Article",
        "type": "article",
        "tags": ["ai"],
        "summary": "Summary here.",
        "key_facts": ["Fact"],
        "cross_links": [],
        "raw_text": "Raw.",
        "error": False,
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com", ingested_date="2026-04-10")

        post = frontmatter.load(path)
        assert post.metadata["title"] == "Test Article"
        assert post.metadata["type"] == "article"
        assert "ai" in post.metadata["tags"]
        assert post.metadata["source"] == "https://example.com"

def test_write_note_error_adds_confidence_low():
    note = {
        "title": "Bad PDF",
        "type": "paper",
        "tags": [],
        "summary": "",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some raw.",
        "error": True,
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="/path/to/file.pdf")

        post = frontmatter.load(path)
        assert post.metadata.get("confidence") == "low"
