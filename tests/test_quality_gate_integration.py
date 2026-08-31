# tests/test_quality_gate_integration.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

pytestmark = pytest.mark.integration

@pytest.mark.asyncio
async def test_pipeline_runs_quality_gate_before_enrichment():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.get_title_by_url.return_value = None
    mock_store.search.return_value = []

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("ingesters.router._is_pdf_url", return_value=False),
        patch("ingesters.news.extract_news", AsyncMock(return_value=MagicMock(
            raw_text="x",
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
    mock_store.get_title_by_url.return_value = None
    mock_store.search.return_value = []

    valid_content = "This is a substantial article with real content that is definitely over five hundred characters long. " * 5

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("ingesters.router._is_pdf_url", return_value=False),
        patch("ingesters.news.extract_news", AsyncMock(return_value=MagicMock(
            raw_text=valid_content,
            images=[],
            content_type="article"
        ))),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch("pipeline.enrich", return_value={
            "title": "Good Article", "type": "article", "tags": [],
            "summary": "This article explores the fundamentals of modern software architecture, focusing on scalable design patterns and practical implementation strategies. The author examines how distributed systems handle failure modes and recovery mechanisms, drawing from real-world case studies of high-availability deployments. Key themes include the balance between consistency and availability in distributed databases, the role of message queues in decoupling services, and techniques for observability in complex microservice environments.\n\nThe piece also covers containerization fundamentals and orchestration best practices, particularly around resource allocation and health checking. Deployment strategies like blue-green releases and canary deployments are analyzed for their risk mitigation properties.",
            "key_facts": [
                "Distributed systems must handle partial failures gracefully through circuit breakers and retry policies.",
                "Message queues enable asynchronous communication between microservices, improving system resilience.",
                "Container orchestration platforms like Kubernetes provide automated scaling and self-healing capabilities.",
            ],
            "cross_links": [],
            "entities": [], "figure_captions": [], "why_saved_hint": "",
            "raw_text": valid_content, "error": False,
        }),
        patch("pipeline.write_note", return_value="/vault/notes/good.md"),
    ):
        messages = []
        async for msg in run_pipeline(url="https://example.com/good"):
            messages.append(msg)

        assert any("Saved" in m for m in messages)
