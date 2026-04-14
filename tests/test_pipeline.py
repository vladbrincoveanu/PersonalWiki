import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_pipeline_url_yields_progress_steps():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.search.return_value = [
        {"metadata": {"title": "Existing Note"}, "path": "notes/existing.md"}
    ]
    mock_store.exists.return_value = False

    with (
        patch("pipeline.extract_url", AsyncMock(return_value="Raw content from URL.")),
        patch("pipeline._is_pdf_url", return_value=False),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch("pipeline.get_store", return_value=mock_store),
        patch(
            "pipeline.enrich",
            return_value={
                "title": "Test Note",
                "type": "article",
                "tags": ["ai"],
                "summary": "Summary.",
                "key_facts": ["Fact"],
                "cross_links": ["existing-note"],
                "raw_text": "Raw.",
                "error": False,
            },
        ),
        patch("pipeline.write_note", return_value="/vault/notes/test-note.md"),
    ):
        messages = []
        async for msg in run_pipeline(url="https://example.com"):
            messages.append(msg)

    assert any("Extracting" in m for m in messages)
    assert any("similar" in m.lower() for m in messages)
    assert any("Minimax" in m for m in messages)
    assert any("Saved" in m for m in messages)


@pytest.mark.asyncio
async def test_pipeline_duplicate_url_detected():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = True

    with patch("pipeline.get_store", return_value=mock_store):
        messages = []
        async for msg in run_pipeline(url="https://already-ingested.com"):
            messages.append(msg)

    assert any("already exists" in m.lower() for m in messages)
    assert not any("Extracting" in m for m in messages)


@pytest.mark.asyncio
async def test_pipeline_handles_extraction_error():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("pipeline.extract_url", AsyncMock(side_effect=ValueError("unreachable"))),
    ):
        messages = []
        async for msg in run_pipeline(url="https://bad-url.com"):
            messages.append(msg)

    assert any("Error" in m or "error" in m for m in messages)


@pytest.mark.asyncio
async def test_pipeline_pdf_url_passes_images_to_writer():
    from pipeline import run_pipeline
    from ingesters.pdf import PdfExtractResult

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    fake_result = PdfExtractResult(
        markdown="# Paper\n\n<!-- image --> some content " + "x" * 300,
        low_quality=False,
        images=[b"fakepng1", b"fakepng2"],
    )

    written_images = []

    def capture_write_note(note, source, images=(), entity_statuses=()):
        written_images.extend(images)
        return "/vault/notes/paper.md"

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("pipeline._is_pdf_url", return_value=True),
        patch("urllib.request.urlretrieve", return_value=("/tmp/fake.pdf", {})),
        patch("pipeline.extract_pdf_full", return_value=fake_result),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch(
            "pipeline.enrich",
            return_value={
                "title": "Paper",
                "type": "paper",
                "tags": [],
                "summary": "S.",
                "key_facts": [],
                "cross_links": [],
                "raw_text": "raw",
                "error": False,
            },
        ),
        patch("pipeline.write_note", side_effect=capture_write_note),
        patch("asyncio.to_thread", new_callable=MagicMock) as mock_to_thread,
    ):
        # Make asyncio.to_thread return the fake_result for extract_pdf_full
        # and delegate normally for enrich (synchronous mock above handles it)
        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        mock_to_thread.side_effect = fake_to_thread

        messages = []
        async for msg in run_pipeline(url="https://arxiv.org/pdf/2510.18518"):
            messages.append(msg)

    assert written_images == [b"fakepng1", b"fakepng2"]
    assert any("Saved" in m for m in messages)


@pytest.mark.asyncio
async def test_pipeline_runs_entity_status_search():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("pipeline._is_pdf_url", return_value=False),
        patch("pipeline.extract_url", AsyncMock(return_value="Raw content from URL.")),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch(
            "pipeline.enrich",
            return_value={
                "title": "Test Paper",
                "type": "paper",
                "tags": [],
                "summary": "A summary.",
                "key_facts": [],
                "cross_links": [],
                "entities": [{"name": "PyTorch", "slug": "pytorch", "type": "library"}],
                "figure_captions": [],
                "why_saved_hint": "",
                "raw_text": "Some content.",
                "error": False,
            },
        ),
        patch("pipeline.fetch_entity_status") as mock_status,
        patch("pipeline.write_note", return_value="/vault/notes/test.md"),
    ):
        mock_status.return_value = [
            {
                "name": "PyTorch",
                "slug": "pytorch",
                "version": "v2.5.1",
                "status": "actively maintained",
                "source": "PyPI",
            },
        ]

        messages = []
        async for msg in run_pipeline(url="https://example.com/test"):
            messages.append(msg)

        mock_status.assert_called_once()
        assert any("Saved" in r for r in messages)


@pytest.mark.asyncio
async def test_pipeline_calls_detect_gaps_and_attaches_gap_entities():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    enriched_note = {
        "title": "Test Note", "type": "article", "tags": ["ai"],
        "summary": "Summary.", "key_facts": ["Fact"],
        "cross_links": [], "raw_text": "Raw.", "error": False,
        "entities": [{"name": "MissingEntity", "slug": "missing-entity"}],
    }

    with patch("pipeline.get_store", return_value=mock_store), \
         patch("pipeline.extract_url", AsyncMock(return_value="Raw content.")), \
         patch("pipeline._is_pdf_url", return_value=False), \
         patch("pipeline.embed", return_value=[0.1] * 384), \
         patch("pipeline.enrich", return_value=enriched_note), \
         patch("pipeline.write_note", return_value="/vault/notes/test-note.md"), \
         patch("pipeline.detect_gaps", return_value=["MissingEntity"]) as mock_detect, \
         patch("pipeline.asyncio.create_task") as mock_create_task:

        messages = []
        async for msg in run_pipeline(url="https://example.com"):
            messages.append(msg)

        mock_detect.assert_called_once_with(enriched_note["entities"])
        assert any("Saved" in m for m in messages)


@pytest.mark.asyncio
async def test_pipeline_no_gap_searches_when_no_gaps():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    enriched_note = {
        "title": "Test Note", "type": "article", "tags": [],
        "summary": "S.", "key_facts": [], "cross_links": [], "raw_text": "Raw.", "error": False,
        "entities": [],
    }

    with patch("pipeline.get_store", return_value=mock_store), \
         patch("pipeline.extract_url", AsyncMock(return_value="Raw content.")), \
         patch("pipeline._is_pdf_url", return_value=False), \
         patch("pipeline.embed", return_value=[0.1] * 384), \
         patch("pipeline.enrich", return_value=enriched_note), \
         patch("pipeline.write_note", return_value="/vault/notes/test-note.md"), \
         patch("pipeline.detect_gaps", return_value=[]) as mock_detect, \
         patch("pipeline.asyncio.create_task") as mock_create_task:

        async for _ in run_pipeline(url="https://example.com"):
            pass

        mock_detect.assert_called_once()
        mock_create_task.assert_not_called()
