"""Tests for typed note templates (video, paper, article)."""
import re
import struct
import tempfile
import zlib
from pathlib import Path
from unittest.mock import patch

import frontmatter

from vault.writer import write_note


def _minimal_png() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    raw = b"\x00\xff\x00\x00"
    compressed = zlib.compress(raw)
    idat_crc = zlib.crc32(b"IDAT" + compressed)
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)
    iend_crc = zlib.crc32(b"IEND")
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    return sig + ihdr + idat + iend


# =============================================================================
# Video template tests
# =============================================================================


def test_video_body_has_required_sections():
    """Video notes must contain all required section headers."""
    note = {
        "title": "Test Video",
        "type": "video",
        "tags": [],
        "summary": "A fascinating video.",
        "key_facts": ["Fact one", "Fact two"],
        "cross_links": [],
        "raw_text": "Full transcript here.",
        "error": False,
        "chapters": [{"time": "0:00", "title": "Intro"}, {"time": "1:30", "title": "Main Content"}],
        "quotes": [{"text": "A great quote.", "speaker": "Speaker A"}],
        "topics": ["topic1", "topic2"],
        "why_saved_hint": "Saved for reference.",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        assert "## Summary" in body
        assert "## Timestamped Chapters" in body
        assert "## Key Quotes" in body
        assert "## Topics Covered" in body
        assert "## Why I Saved This" in body
        assert "## Transcript (Selected Sections)" in body


def test_video_body_chapters_formatted():
    """Video chapters must render as - [time] title."""
    note = {
        "title": "Test Video",
        "type": "video",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Transcript.",
        "error": False,
        "chapters": [
            {"time": "0:00", "title": "Introduction"},
            {"time": "5:30", "title": "Deep Dive"},
        ],
        "quotes": [],
        "topics": [],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        assert "- [0:00] Introduction" in body
        assert "- [5:30] Deep Dive" in body


def test_video_body_quotes_formatted():
    """Video key quotes must render as blockquotes."""
    note = {
        "title": "Test Video",
        "type": "video",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Transcript.",
        "error": False,
        "chapters": [],
        "quotes": [
            {"text": "This is a key insight.", "speaker": "Dr. Smith"},
            {"text": "Another important point.", "speaker": "Host"},
        ],
        "topics": [],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        assert '> "This is a key insight." — Dr. Smith' in body
        assert '> "Another important point." — Host' in body


def test_video_body_topics_formatted():
    """Video topics must render as bullet list."""
    note = {
        "title": "Test Video",
        "type": "video",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Transcript.",
        "error": False,
        "chapters": [],
        "quotes": [],
        "topics": ["machine learning", "reinforcement learning", "LLMs"],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        topics_section = body.split("## Topics Covered")[1].split("##")[0]
        assert "- machine learning" in topics_section
        assert "- reinforcement learning" in topics_section
        assert "- LLMs" in topics_section


def test_video_body_transcript_wrapped_in_details():
    """Video transcript must be wrapped in <details> tag."""
    note = {
        "title": "Test Video",
        "type": "video",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Full raw transcript content here.",
        "error": False,
        "chapters": [],
        "quotes": [],
        "topics": [],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        assert "<details>" in body
        assert "<summary>Full transcript</summary>" in body
        assert "Full raw transcript content here." in body
        assert "</details>" in body


def test_video_body_why_saved_with_edit_hint():
    """Video why_saved must include the _(edit this)_ hint."""
    note = {
        "title": "Test Video",
        "type": "video",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Transcript.",
        "error": False,
        "chapters": [],
        "quotes": [],
        "topics": [],
        "why_saved_hint": "Because it's relevant.",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        assert "## Why I Saved This" in body
        assert "Because it's relevant." in body
        assert "_(edit this)_" in body


# =============================================================================
# Paper template tests
# =============================================================================


def test_paper_body_has_required_sections():
    """Paper notes must contain all required section headers."""
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A research summary.",
        "key_facts": ["Finding A", "Finding B"],
        "cross_links": ["related-note"],
        "raw_text": "Extracted raw text.",
        "error": False,
        "entities": [
            {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
        ],
        "figure_captions": [],
        "why_saved_hint": "Saved for research.",
        "tldr": "Too long, didn't read.",
        "method": "Used deep learning.",
        "benchmarks": "SOTA on 3 benchmarks.",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        assert "## Summary" in body
        assert "## TL;DR" in body
        assert "## Key Findings" in body
        assert "## Method / Architecture" in body
        assert "## Benchmarks" in body
        assert "## Entities" in body
        assert "## My Knowledge Says" in body
        assert "## Raw Extract" in body


def test_paper_body_tldr_formatted():
    """Paper TL;DR must be italicized."""
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Raw.",
        "error": False,
        "entities": [],
        "figure_captions": [],
        "why_saved_hint": "",
        "tldr": "Quick summary of the paper.",
        "method": "",
        "benchmarks": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        tldr_section = body.split("## TL;DR")[1].split("##")[0]
        assert "_Quick summary of the paper._" in tldr_section


def test_paper_body_key_findings_as_bullets():
    """Paper key findings must render as bullet list."""
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "Summary.",
        "key_facts": ["Fact 1: Important result", "Fact 2: Another insight"],
        "cross_links": [],
        "raw_text": "Raw.",
        "error": False,
        "entities": [],
        "figure_captions": [],
        "why_saved_hint": "",
        "tldr": "",
        "method": "",
        "benchmarks": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        findings_section = body.split("## Key Findings")[1].split("##")[0]
        assert "- Fact 1: Important result" in findings_section
        assert "- Fact 2: Another insight" in findings_section


def test_paper_body_entities_section_wikilinks():
    """Paper entities must render as wikilinks."""
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Raw.",
        "error": False,
        "entities": [
            {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
            {"name": "ROC Analysis", "slug": "roc-analysis", "type": "concept"},
        ],
        "figure_captions": [],
        "why_saved_hint": "",
        "tldr": "",
        "method": "",
        "benchmarks": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        entities_section = body.split("## Entities")[1].split("##")[0]
        assert "[[MIMIC-IV]]" in entities_section
        assert "[[ROC Analysis]]" in entities_section


def test_paper_body_my_knowledge_says_wikilinks():
    """Paper my knowledge says must render cross_links as wikilinks."""
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": ["related-note-1", "related-note-2"],
        "raw_text": "Raw.",
        "error": False,
        "entities": [],
        "figure_captions": [],
        "why_saved_hint": "",
        "tldr": "",
        "method": "",
        "benchmarks": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        knowledge_section = body.split("## My Knowledge Says")[1].split("##")[0]
        assert "[[related-note-1]]" in knowledge_section
        assert "[[related-note-2]]" in knowledge_section


def test_paper_body_raw_extract_wrapped_in_details():
    """Paper raw extract must be wrapped in <details> tag."""
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Original extracted paper content.",
        "error": False,
        "entities": [],
        "figure_captions": [],
        "why_saved_hint": "",
        "tldr": "",
        "method": "",
        "benchmarks": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        assert "<details>" in body
        assert "<summary>Original extracted text</summary>" in body
        assert "Original extracted paper content." in body
        assert "</details>" in body


def test_paper_body_recent_developments_via_entity_statuses():
    """Paper recent developments must come from entity_statuses param."""
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Raw.",
        "error": False,
        "entities": [
            {"name": "PyTorch", "slug": "pytorch", "type": "library"},
        ],
        "figure_captions": [],
        "why_saved_hint": "",
        "tldr": "",
        "method": "",
        "benchmarks": "",
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
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(
                note, source="https://example.com", entity_statuses=entity_statuses
            )

        post = frontmatter.load(path)
        body = post.content
        assert "## Recent Developments" in body
        assert "PyTorch" in body
        assert "v2.5.1" in body
        assert "actively maintained" in body


def test_paper_body_no_recent_developments_when_empty_statuses():
    """Paper with no entity_statuses must not have recent developments."""
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Raw.",
        "error": False,
        "entities": [
            {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
        ],
        "figure_captions": [],
        "why_saved_hint": "",
        "tldr": "",
        "method": "",
        "benchmarks": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com", entity_statuses=[])

        post = frontmatter.load(path)
        body = post.content
        assert "## Recent Developments" not in body


# =============================================================================
# Article template tests (backward compat — existing template)
# =============================================================================


def test_article_body_unchanged_structure():
    """Article notes keep the existing template structure."""
    note = {
        "title": "Test Article",
        "type": "article",
        "tags": [],
        "summary": "Article summary.",
        "key_facts": ["Fact one"],
        "cross_links": ["other-note"],
        "raw_text": "Raw content.",
        "error": False,
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        # Existing structure
        assert "## Summary" in body
        assert "## Key Facts" in body
        assert "## My Knowledge Says" in body
        assert "[[other-note]]" in body
        assert "## Raw Extract" in body
        # No extra sections
        assert "## TL;DR" not in body
        assert "## Timestamped Chapters" not in body


def test_article_body_recent_developments_via_entity_statuses():
    """Article recent developments must come from entity_statuses param."""
    note = {
        "title": "Test Article",
        "type": "article",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Raw.",
        "error": False,
        "entities": [
            {"name": "PyTorch", "slug": "pytorch", "type": "library"},
        ],
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
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(
                note, source="https://example.com", entity_statuses=entity_statuses
            )

        post = frontmatter.load(path)
        body = post.content
        assert "## Recent Developments" in body
        assert "PyTorch" in body
        assert "v2.5.1" in body


def test_article_body_why_saved_when_hint_present():
    """Article why_saved section must include the _(edit this)_ hint."""
    note = {
        "title": "Test Article",
        "type": "article",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Raw.",
        "error": False,
        "entities": [],
        "why_saved_hint": "Because relevant.",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        assert "## Why I Saved This" in body
        assert "Because relevant." in body
        assert "_(edit this)_" in body


def test_article_body_no_why_saved_when_empty():
    """Article with no why_saved_hint must not have the section."""
    note = {
        "title": "Test Article",
        "type": "article",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Raw.",
        "error": False,
        "entities": [],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        assert "## Why I Saved This" not in body


# =============================================================================
# Dispatcher tests
# =============================================================================


def test_dispatcher_unknown_type_falls_back_to_article():
    """Unknown note types must fall back to article template."""
    note = {
        "title": "Unknown Type Note",
        "type": "unknown_type",
        "tags": [],
        "summary": "Summary.",
        "key_facts": ["Fact one"],
        "cross_links": [],
        "raw_text": "Raw.",
        "error": False,
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        # Should use article template structure
        assert "## Summary" in body
        assert "## Key Facts" in body
        assert "## Raw Extract" in body
        # Should NOT have video/paper specific sections
        assert "## Timestamped Chapters" not in body
        assert "## TL;DR" not in body


def test_article_with_entities_still_has_entities_section():
    """Article with entities must still render the ## Entities section."""
    note = {
        "title": "Test Article",
        "type": "article",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Raw.",
        "error": False,
        "entities": [
            {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
        ],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        body = post.content
        assert "## Entities" in body
        assert "[[MIMIC-IV]]" in body
