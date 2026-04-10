import pytest
from unittest.mock import patch, AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_pipeline_url_yields_progress_steps():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.search.return_value = [{"metadata": {"title": "Existing Note"}, "path": "notes/existing.md"}]
    mock_store.exists.return_value = False

    with patch("pipeline.extract_url", AsyncMock(return_value="Raw content from URL.")), \
         patch("pipeline.extract_pdf"), \
         patch("pipeline.embed", return_value=[0.1] * 384), \
         patch("pipeline.get_store", return_value=mock_store), \
         patch("pipeline.enrich", return_value={
             "title": "Test Note", "type": "article", "tags": ["ai"],
             "summary": "Summary.", "key_facts": ["Fact"],
             "cross_links": ["existing-note"], "raw_text": "Raw.", "error": False,
         }), \
         patch("pipeline.write_note", return_value="/vault/notes/test-note.md"):

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

    with patch("pipeline.get_store", return_value=mock_store), \
         patch("pipeline.extract_url", AsyncMock(side_effect=ValueError("unreachable"))):

        messages = []
        async for msg in run_pipeline(url="https://bad-url.com"):
            messages.append(msg)

    assert any("Error" in m or "error" in m for m in messages)
