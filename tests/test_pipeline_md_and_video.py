# tests/test_pipeline_md_and_video.py
"""Integration tests for MD file ingestion, video semantic chunking, and async gap search."""
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


@pytest.mark.asyncio
async def test_pipeline_md_file_creates_note():
    """MD file → extract_markdown → enrich → write note → Saved."""
    import pipeline as pipeline_module
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.get_title_by_url.return_value = None
    mock_store.search.return_value = []

    # Content must exceed _MIN_ARTICLE_CHARS=500 in quality_gate.py
    md_content = (
        "# Test Markdown Document\n\n"
        "This is a substantial markdown document with real content for testing purposes. "
        "It contains multiple paragraphs of meaningful text that provide information. "
        "The content is designed to be long enough to pass the quality gate check.\n\n"
        "## Section One\n\n"
        "Here is some paragraph content that provides meaningful information. "
        "This section contains detailed explanations about various topics. "
        "It helps demonstrate that the markdown extraction works correctly.\n\n"
        "## Section Two\n\n"
        "Additional content with more paragraphs and detailed explanations. "
        "This section continues the discussion with more useful information. "
        "It ensures the document has sufficient length for processing.\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir(parents=True)

        md_file = tmp_path / "test_doc.md"
        md_file.write_text(md_content)

        # Enrichment result with sufficient prose (>=300 chars in summary + key_facts)
        enrich_result = {
            "title": "Test MD Note",
            "type": "document",
            "tags": ["test"],
            "summary": (
                "This markdown document was successfully processed through the pipeline for testing purposes. "
                "It demonstrates the complete flow from markdown extraction through enrichment to note creation. "
                "The pipeline handles the content appropriately and produces a well-structured note."
            ),
            "key_facts": [
                "The markdown extraction captured all paragraphs and headings correctly.",
                "The pipeline enriched the document with comprehensive metadata including tags and entities.",
                "The content passed both Track A and Track B quality gates successfully.",
            ],
            "cross_links": [],
            "entities": [],
            "figure_captions": [],
            "why_saved_hint": "",
            "raw_text": md_content,
            "error": False,
        }

        original_write_note = pipeline_module.write_note
        original_enrich = pipeline_module.enrich

        def mock_write_note(note, source, images=(), entity_statuses=()):
            from vault.writer import slugify
            slug = slugify(note.get("title", "untitled"))
            filepath = notes_dir / f"{slug}.md"
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text("# Mock Note\nContent.")
            return str(filepath)

        pipeline_module.enrich = lambda *args, **kwargs: enrich_result
        pipeline_module.write_note = mock_write_note

        try:
            with patch.object(pipeline_module, 'get_store', return_value=mock_store), \
                 patch.object(pipeline_module, 'embed', return_value=[0.1] * 384):
                messages = []
                async for msg in run_pipeline(md_path=str(md_file)):
                    messages.append(msg)

            assert any("Saved" in m for m in messages), f"No Saved in messages: {messages}"
            note_file = notes_dir / "test-md-note.md"
            assert note_file.exists(), f"Note not written: {list(notes_dir.iterdir())}"
        finally:
            pipeline_module.enrich = original_enrich
            pipeline_module.write_note = original_write_note


@pytest.mark.asyncio
async def test_pipeline_video_uses_semantic_chunking():
    """Video with long transcript → semantic_chunk path → enrich_video_synthesis."""
    import pipeline as pipeline_module
    from pipeline import run_pipeline
    from core import minimax_client

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.get_title_by_url.return_value = None
    mock_store.search.return_value = []

    # raw_text must exceed _MIN_CHUNK_SIZE (60_000) to trigger semantic chunking
    long_transcript = ("This is a sentence about machine learning. " * 2000)

    # Fake chunks that semantic_chunk would return
    class FakeChunk:
        def __init__(self, text, start, end, num):
            self.text = text
            self.start_index = start
            self.end_index = end
            self.chunk_number = num

    fake_chunks = [
        FakeChunk("Chunk 1 about ML. " * 500, 0, 40000, 1),
        FakeChunk("Chunk 2 about AI. " * 500, 40000, 80000, 2),
    ]

    # Per-chunk enrichment result
    chunk_enrich_result = {
        "title": "Chunk 1",
        "summary": "First chunk summary about machine learning concepts and their practical applications in modern AI systems.",
        "chapters": [{"time": "00:00", "title": "Introduction"}],
        "key_quotes": [],
        "entities": [],
        "key_facts": [
            "Machine learning fundamentals are explained thoroughly in this section.",
            "Neural networks and deep learning architectures are covered in detail.",
        ],
        "topics_covered": ["ml", "ai", "deep learning"],
        "tags": ["ml", "ai"],
        "cross_links": [],
        "why_saved_hint": "",
        "raw_text": "Chunk 1 about ML. " * 500,
        "error": False,
    }

    # Video synthesis result
    synthesis_result = {
        "title": "Video Test",
        "type": "video",
        "tags": ["test"],
        "summary": "This video covers machine learning topics in depth with detailed explanations of key concepts and their real-world applications.",
        "key_facts": [
            "The video explains fundamental machine learning concepts thoroughly with practical examples.",
            "Neural networks and deep learning architectures are discussed in comprehensive detail.",
            "Real-world applications demonstrate how these concepts are applied in production systems.",
        ],
        "cross_links": [],
        "entities": [],
        "chapters": [{"time": "00:00", "title": "Introduction"}],
        "key_quotes": [],
        "topics_covered": ["machine learning", "neural networks", "deep learning"],
        "figure_captions": [],
        "why_saved_hint": "",
        "raw_text": long_transcript,
        "error": False,
    }

    # Mock Document for extract
    class MockDoc:
        def __init__(self):
            self.raw_text = long_transcript
            self.images = []
            self.content_type = "video"

    async def mock_extract(url):
        return MockDoc()

    # Save originals
    original_extract = pipeline_module.extract
    original_enrich = pipeline_module.enrich

    # Patch at core.minimax_client level (not pipeline) because pipeline imports these locally inside the video branch
    mock_semantic_chunk = MagicMock(return_value=fake_chunks)
    mock_enrich_video_synthesis = MagicMock(return_value=synthesis_result)

    pipeline_module.extract = mock_extract
    pipeline_module.enrich = lambda *args, **kwargs: chunk_enrich_result

    try:
        with patch.object(pipeline_module, 'get_store', return_value=mock_store), \
             patch.object(pipeline_module, 'embed', return_value=[0.1] * 384), \
             patch.object(minimax_client, 'semantic_chunk', mock_semantic_chunk), \
             patch.object(minimax_client, 'enrich_video_synthesis', mock_enrich_video_synthesis):
            messages = []
            async for msg in run_pipeline(url="https://youtube.com/watch?v=abc123DEF12"):
                messages.append(msg)

        assert any("Saved" in m for m in messages), f"No Saved in messages: {messages}"
        # Verify chunking path was taken
        mock_semantic_chunk.assert_called_once()
        mock_enrich_video_synthesis.assert_called_once()
    finally:
        pipeline_module.extract = original_extract
        pipeline_module.enrich = original_enrich


@pytest.mark.asyncio
async def test_gap_search_runs_without_crashing():
    """Pipeline fires _run_gap_searches as async task without crashing."""
    import pipeline as pipeline_module
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.get_title_by_url.return_value = None
    mock_store.search.return_value = []

    # Mock Document for extract
    class MockDoc:
        def __init__(self):
            self.raw_text = "This article is about programming and software engineering topics. " * 50
            self.images = []
            self.content_type = "article"

    async def mock_extract(url):
        return MockDoc()

    def mock_detect_gaps(entities):
        return ["MissingTopic"]

    enrich_result = {
        "title": "Test Gap Search",
        "type": "article",
        "tags": [],
        "summary": "This is a detailed article about programming concepts and software engineering practices that provides valuable information for developers.",
        "key_facts": [
            "Programming requires understanding of algorithms and data structures for efficient problem solving.",
            "Software engineering involves systematic development processes and best practices.",
            "Modern software development incorporates agile methodologies and continuous integration.",
        ],
        "cross_links": [],
        "entities": [{"name": "MissingTopic", "slug": "missing-topic", "type": "concept"}],
        "figure_captions": [],
        "why_saved_hint": "",
        "raw_text": "This article is about programming and software engineering topics. " * 50,
        "error": False,
    }

    # Save originals
    original_extract = pipeline_module.extract
    original_enrich = pipeline_module.enrich
    original_detect_gaps = pipeline_module.detect_gaps

    pipeline_module.extract = mock_extract
    pipeline_module.enrich = lambda *args, **kwargs: enrich_result
    pipeline_module.detect_gaps = mock_detect_gaps

    try:
        with patch.object(pipeline_module, 'get_store', return_value=mock_store), \
             patch.object(pipeline_module, 'embed', return_value=[0.1] * 384), \
             patch.object(pipeline_module, 'write_note', return_value="/vault/notes/test-gap.md"):
            messages = []
            async for msg in run_pipeline(url="https://example.com/test"):
                messages.append(msg)

        # Pipeline completes without error
        assert any("Saved" in m for m in messages), f"No Saved in messages: {messages}"
    finally:
        pipeline_module.extract = original_extract
        pipeline_module.enrich = original_enrich
        pipeline_module.detect_gaps = original_detect_gaps
