# tests/test_quality_gate_integration.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_pipeline_runs_quality_gate_before_enrichment():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("pipeline._is_pdf_url", return_value=False),
        patch("ingesters.news.extract_news", AsyncMock(return_value=MagicMock(
            raw_text="Short",
            images=[],
            content_type="article"
        ))),
        patch("pipeline.enrich") as mock_enrich,
    ):
        messages = []
        async for msg in run_pipeline(url="https://example.com/thin"):
            messages.append(msg)

        mock_enrich.assert_not_called()
        assert any("Skipped" in m or "thin" in m.lower() for m in messages)

@pytest.mark.asyncio
async def test_pipeline_passes_valid_content_through_gate():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    valid_content = "This is a substantial article with real content that is definitely over five hundred characters long. " * 5

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("pipeline._is_pdf_url", return_value=False),
        patch("ingesters.news.extract_news", AsyncMock(return_value=MagicMock(
            raw_text=valid_content,
            images=[],
            content_type="article"
        ))),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch("pipeline.enrich", return_value={
            "title": "Good Article", "type": "article", "tags": [],
            "summary": ".", "key_facts": [], "cross_links": [],
            "entities": [], "figure_captions": [], "why_saved_hint": "",
            "raw_text": valid_content, "error": False,
        }),
        patch("pipeline.write_note", return_value="/vault/notes/good.md"),
    ):
        messages = []
        async for msg in run_pipeline(url="https://example.com/good"):
            messages.append(msg)

        assert any("Saved" in m for m in messages)