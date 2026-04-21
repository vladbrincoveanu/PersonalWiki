import struct
import tempfile
import zlib
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
            path = write_note(
                note, source="https://example.com", ingested_date="2026-04-10"
            )

        post = frontmatter.load(path)
        assert post.metadata["title"] == "Test Article"
        assert post.metadata["type"] == "article"
        assert "ai" in post.metadata["tags"]
        assert post.metadata["source"] == "https://example.com"


def _minimal_png() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    raw = b"\x00\xff\x00\x00"  # filter byte + 1 RGB pixel
    compressed = zlib.compress(raw)
    idat_crc = zlib.crc32(b"IDAT" + compressed)
    idat = (
        struct.pack(">I", len(compressed))
        + b"IDAT"
        + compressed
        + struct.pack(">I", idat_crc)
    )
    iend_crc = zlib.crc32(b"IEND")
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    return sig + ihdr + idat + iend


def test_write_note_saves_images_and_replaces_placeholders():
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Intro <!-- image --> middle <!-- image --> end.",
        "error": False,
    }
    fake_png = _minimal_png()
    images = [fake_png, fake_png]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()

        with (
            patch("vault.writer.NOTES_DIR", notes_dir),
            patch("vault.writer.VAULT_PATH", tmp_path),
        ):
            path = write_note(
                note, source="https://example.com/paper.pdf", images=images
            )

        post = frontmatter.load(path)
        body = post.content

        # Both placeholders replaced
        assert "<!-- image -->" not in body
        assert "![[attachments/test-paper/figure-1.png]]" in body
        assert "![[attachments/test-paper/figure-2.png]]" in body

        # Image files exist
        assert (tmp_path / "attachments" / "test-paper" / "figure-1.png").exists()
        assert (tmp_path / "attachments" / "test-paper" / "figure-2.png").exists()


def test_write_note_no_images_unchanged():
    """write_note without images keeps <!-- image --> as-is and creates no attachments dir."""
    note = {
        "title": "Web Article",
        "type": "article",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some text <!-- image --> here.",
        "error": False,
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()

        with (
            patch("vault.writer.NOTES_DIR", notes_dir),
            patch("vault.writer.VAULT_PATH", tmp_path),
        ):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        assert "<!-- image -->" in post.content
        assert not (tmp_path / "attachments").exists()


def test_write_note_entities_section():
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some content.",
        "error": False,
        "entities": [
            {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
            {"name": "ROC Analysis", "slug": "roc-analysis", "type": "concept"},
        ],
        "figure_captions": [],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with (
            patch("vault.writer.NOTES_DIR", notes_dir),
            patch("vault.writer.VAULT_PATH", tmp_path),
        ):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        assert "## Entities" in post.content
        assert "[[MIMIC-IV]]" in post.content
        assert "[[ROC Analysis]]" in post.content


def test_write_note_why_saved_section():
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some content.",
        "error": False,
        "entities": [],
        "figure_captions": [],
        "why_saved_hint": "Relevant to my robot learning work.",
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with (
            patch("vault.writer.NOTES_DIR", notes_dir),
            patch("vault.writer.VAULT_PATH", tmp_path),
        ):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        assert "## Why I Saved This" in post.content
        assert "Relevant to my robot learning work." in post.content
        assert "_(edit this)_" in post.content


def test_write_note_figure_captions_injected():
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Intro <!-- image --> middle <!-- image --> end.",
        "error": False,
        "entities": [],
        "figure_captions": ["Model architecture overview", "Training reward curves"],
        "why_saved_hint": "",
    }
    images = [_minimal_png(), _minimal_png()]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with (
            patch("vault.writer.NOTES_DIR", notes_dir),
            patch("vault.writer.VAULT_PATH", tmp_path),
        ):
            path = write_note(note, source="https://example.com", images=images)

        post = frontmatter.load(path)
        assert "*Figure 1: Model architecture overview.*" in post.content
        assert "*Figure 2: Training reward curves.*" in post.content
        assert "<!-- image -->" not in post.content


def test_write_note_fewer_captions_than_figures_no_error():
    """Figures beyond the caption list are rendered without a caption line."""
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "<!-- image --> mid <!-- image --> end.",
        "error": False,
        "entities": [],
        "figure_captions": ["Caption for figure one only"],
        "why_saved_hint": "",
    }
    images = [_minimal_png(), _minimal_png()]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with (
            patch("vault.writer.NOTES_DIR", notes_dir),
            patch("vault.writer.VAULT_PATH", tmp_path),
        ):
            path = write_note(note, source="https://example.com", images=images)

        post = frontmatter.load(path)
        assert "*Figure 1: Caption for figure one only.*" in post.content
        assert "![[attachments/test-paper/figure-2.png]]" in post.content
        # Figure 2 has no caption line
        assert "*Figure 2:" not in post.content


def test_write_note_entity_without_slug_excluded_from_wikilinks():
    """Entities with a name but no slug must not produce a wikilink (no stub would be created)."""
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some content.",
        "error": False,
        "entities": [
            {"name": "ValidEntity", "slug": "valid-entity", "type": "concept"},
            {"name": "NoSlugEntity", "slug": "", "type": "concept"},
        ],
        "figure_captions": [],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with (
            patch("vault.writer.NOTES_DIR", notes_dir),
            patch("vault.writer.VAULT_PATH", tmp_path),
        ):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        assert "[[ValidEntity]]" in post.content
        assert "[[NoSlugEntity]]" not in post.content


def test_write_note_no_entities_section_when_empty():
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some content.",
        "error": False,
        "entities": [],
        "figure_captions": [],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with (
            patch("vault.writer.NOTES_DIR", notes_dir),
            patch("vault.writer.VAULT_PATH", tmp_path),
        ):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        assert "## Entities" not in post.content
        assert "## Why I Saved This" not in post.content


def test_write_note_recent_developments_section():
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some content.",
        "error": False,
        "entities": [
            {"name": "PyTorch", "slug": "pytorch", "type": "library"},
            {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
        ],
        "figure_captions": [],
        "why_saved_hint": "",
    }
    entity_statuses = [
        {
            "name": "PyTorch",
            "slug": "pytorch",
            "version": "v2.5.1",
            "status": "actively maintained",
            "source": "PyPI",
        },
    ]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with (
            patch("vault.writer.NOTES_DIR", notes_dir),
            patch("vault.writer.VAULT_PATH", tmp_path),
        ):
            path = write_note(
                note, source="https://example.com", entity_statuses=entity_statuses
            )

        post = frontmatter.load(path)
        assert "## Recent Developments" in post.content
        assert "PyTorch" in post.content
        assert "v2.5.1" in post.content
        assert "actively maintained" in post.content


def test_write_note_no_recent_developments_when_empty_statuses():
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some content.",
        "error": False,
        "entities": [
            {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
        ],
        "figure_captions": [],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with (
            patch("vault.writer.NOTES_DIR", notes_dir),
            patch("vault.writer.VAULT_PATH", tmp_path),
        ):
            path = write_note(note, source="https://example.com", entity_statuses=[])

        post = frontmatter.load(path)
        assert "## Recent Developments" not in post.content


def test_build_video_body_uses_correct_field_names():
    """_build_video_body must use 'key_quotes' and 'topics_covered', not 'quotes' and 'topics'."""
    from vault.writer import _build_video_body

    note = {
        "summary": "Test summary",
        "type": "video",
        # These are the actual field names from MiniMax API
        "key_quotes": [{"text": "Something important", "speaker": "Dr. Smith"}],
        "topics_covered": ["machine learning", "AI safety"],
        "chapters": [{"time": "00:00", "title": "Intro"}],
    }
    body = _build_video_body(note)

    # key_quotes content must appear
    assert "Something important" in body
    assert "Dr. Smith" in body
    # topics_covered content must appear
    assert "machine learning" in body
    assert "AI safety" in body
    # Old wrong field names must NOT create spurious sections
    assert "## Key Quotes\n\n_" not in body  # would appear if quotes==[] and key_quotes ignored


def test_build_video_body_missing_quote_keys_no_crash():
    """Missing 'text' or 'speaker' in key_quotes must not raise KeyError."""
    from vault.writer import _build_video_body

    note = {
        "summary": "Test",
        "type": "video",
        "key_quotes": [
            {"text": "Valid quote"},          # missing 'speaker'
            {"speaker": "Someone"},            # missing 'text'
            {"text": "Valid", "speaker": "Person"},  # valid
            {},                                 # empty dict
        ],
    }
    # Must not raise KeyError
    body = _build_video_body(note)
    assert "Valid quote" in body
    assert "Valid" in body


def test_write_note_source_keyword_in_frontmatter():
    """write_note() with source_keyword should write it to frontmatter."""
    note = {
        "title": "Test Discovery Note",
        "type": "article",
        "tags": [],
        "summary": "A test summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some content.",
        "error": False,
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(
                note,
                source="https://example.com",
                source_keyword="machine learning",
            )

        post = frontmatter.load(path)
        assert post.metadata.get("source_keyword") == "machine learning"


def test_write_note_source_keyword_omitted_no_frontmatter_key():
    """write_note() without source_keyword should not have source_keyword in frontmatter."""
    note = {
        "title": "Test Note No Keyword",
        "type": "article",
        "tags": [],
        "summary": "A test summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some content.",
        "error": False,
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        assert "source_keyword" not in post.metadata
