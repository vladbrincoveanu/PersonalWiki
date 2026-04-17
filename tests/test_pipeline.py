import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_pipeline_url_yields_progress_steps():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.search.return_value = [
        {"metadata": {"title": "Existing Note"}, "path": "notes/existing.md"}
    ]
    mock_store.exists.return_value = False

    mock_doc = MagicMock()
    mock_doc.raw_text = "Real extracted content from the web page that is definitely over one hundred characters long for testing purposes. " * 5
    mock_doc.images = []

    with (
        patch("ingesters.news.extract_news", AsyncMock(return_value=MagicMock(
            raw_text="Real extracted content from the web page that is definitely over one hundred characters long for testing purposes. " * 5,
            images=[]
        ))),
        patch("pipeline._is_pdf_url", return_value=False),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch("pipeline.get_store", return_value=mock_store),
        patch(
            "pipeline.enrich",
            return_value={
                "title": "Test Note",
                "type": "article",
                "tags": ["ai"],
                "summary": "This is a detailed summary of the test note that provides substantial information. It contains multiple sentences explaining the key points and main takeaways from the content. The summary is comprehensive and informative.",
                "key_facts": [
                    "First key fact is important and informative about the topic.",
                    "Second key fact adds additional context and supporting details.",
                    "Third key fact provides more information about the main subject.",
                ],
                "cross_links": ["existing-note"],
                "raw_text": "Real extracted content from the web page that is definitely over one hundred characters long for testing purposes. " * 5,
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
        patch("ingesters.news.extract_news", AsyncMock(side_effect=ValueError("unreachable"))),
    ):
        messages = []
        async for msg in run_pipeline(url="https://bad-url.com"):
            messages.append(msg)

    assert any("Error" in m or "error" in m for m in messages)


@pytest.mark.asyncio
async def test_pipeline_pdf_url_passes_images_to_writer(tmp_path):
    from pipeline import run_pipeline
    from ingesters.pdf import PdfExtractResult

    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.0\nfake pdf content")

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    fake_result = PdfExtractResult(
        markdown="# Paper\n\n<!-- image --> some content " + "x" * 500,
        low_quality=False,
        images=[b"fakepng1", b"fakepng2"],
    )

    written_images = []

    def capture_write_note(note, source, images=(), entity_statuses=()):
        written_images.extend(images)
        return "/vault/notes/paper.md"

    def fake_urlretrieve(url, filename):
        Path(filename).write_bytes(b"%PDF-1.0\nfake pdf")
        return (filename, {})

    with (
        patch("pipeline.get_store", return_value=mock_store),
        patch("pipeline._is_pdf_url", return_value=True),
        patch("urllib.request.urlretrieve", side_effect=fake_urlretrieve),
        patch("ingesters.pdf.extract_pdf_full", return_value=fake_result),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch(
            "pipeline.enrich",
            return_value={
                "title": "Paper",
                "type": "paper",
                "tags": [],
                "summary": "This paper provides a comprehensive overview of the research topic and its significance in the field. It discusses key findings and contributions.",
                "key_facts": [
                    "First key finding is important and contributes to the field.",
                    "Second key finding provides additional evidence and support.",
                    "Third key finding offers new insights into the topic.",
                ],
                "cross_links": [],
                "raw_text": "# Paper\n\n<!-- image --> some content " + "x" * 500,
                "error": False,
            },
        ),
        patch("pipeline.write_note", side_effect=capture_write_note),
    ):

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
        patch("ingesters.news.extract_news", AsyncMock(return_value=MagicMock(
            raw_text="Real extracted content from the web page that is definitely over one hundred characters long for testing purposes. " * 5,
            images=[]
        ))),
        patch("pipeline.embed", return_value=[0.1] * 384),
        patch(
            "pipeline.enrich",
            return_value={
                "title": "Test Paper",
                "type": "paper",
                "tags": [],
                "summary": "This test paper provides a detailed summary of the research findings and their implications. It covers key aspects of the topic thoroughly.",
                "key_facts": [
                    "First key fact about the research and its significance.",
                    "Second key fact that supports the main argument.",
                    "Third key fact providing additional evidence and context.",
                ],
                "cross_links": [],
                "entities": [{"name": "PyTorch", "slug": "pytorch", "type": "library"}],
                "figure_captions": [],
                "why_saved_hint": "",
                "raw_text": "Real extracted content from the web page that is definitely over one hundred characters long for testing purposes. " * 5,
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
        "summary": "This is a detailed summary of the test note providing substantial information about the key topics. It contains multiple important points and findings.",
        "key_facts": [
            "First key fact that provides important context about the topic.",
            "Second key fact that supports the main discussion and arguments.",
            "Third key fact that adds valuable insights and information.",
        ],
        "cross_links": [], "raw_text": "Real extracted content from the web page that is definitely over one hundred characters long for testing purposes. " * 5, "error": False,
        "entities": [{"name": "MissingEntity", "slug": "missing-entity"}],
    }

    with patch("pipeline.get_store", return_value=mock_store), \
         patch("ingesters.news.extract_news", AsyncMock(return_value=MagicMock(raw_text="Real extracted content from the web page that is definitely over one hundred characters long for testing purposes. " * 5, images=[]))), \
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
        "summary": "This is a detailed summary that provides substantial information about the topic. It contains multiple sentences with important context and key takeaways for the reader.",
        "key_facts": [
            "First key fact contributes important information about the subject and its significance in the broader context.",
            "Second key fact adds additional context and supporting details that reinforce the main points.",
        ],
        "cross_links": [], "raw_text": "Real extracted content from the web page that is definitely over one hundred characters long for testing purposes. " * 5, "error": False,
        "entities": [],
    }

    with patch("pipeline.get_store", return_value=mock_store), \
         patch("ingesters.news.extract_news", AsyncMock(return_value=MagicMock(raw_text="Real extracted content from the web page that is definitely over one hundred characters long for testing purposes. " * 5, images=[]))), \
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


# ─────────────────────────────────────────────────────────────────────────────
# Tests for _gate_enriched_content
# ─────────────────────────────────────────────────────────────────────────────

def test_gate_enriched_content_rejects_thin_prose():
    """Thin enriched content (summary + key_facts under 300 prose chars) is rejected."""
    from pipeline import _gate_enriched_content

    # Very short summary, no key_facts — should fail hard minimum
    note = {"summary": "Short.", "key_facts": []}
    raw_text = "This is some raw text that is long enough to pass the ratio check but the enriched prose is too short."

    passed, prose_chars, prose_ratio = _gate_enriched_content(note, raw_text)
    assert passed is False
    assert prose_chars < 300


def test_gate_enriched_content_rejects_low_prose_ratio():
    """Content where prose ratio < 20%% was previously rejected but ratio check is now disabled.

    The ratio check was disabled because it was rejecting valid YouTube transcripts
    with high timestamp density. The hard minimum (>=300 prose chars) still applies.
    """
    from pipeline import _gate_enriched_content

    # Enriched content has >= 300 prose chars, but raw_text is huge (mostly noise)
    # so ratio = 300 / 5000 = 0.06 < 0.20
    note = {
        "summary": (
            "This summary contains meaningful content that describes the topic. "
            "It provides important context and details about the subject matter. "
            "The information presented is valuable for understanding the key concepts."
        ),
        "key_facts": [
            "First important fact about the topic and its significance.",
            "Second important fact that clarifies the main argument.",
            "Third fact that provides additional supporting details.",
        ],
    }
    # Huge raw_text of mostly noise/timestamps — ratio will be < 0.20
    raw_text = "00:00:00 --> 00:00:01\n[music playing]\n00:00:01 --> 00:00:02\n[silence]\n" * 100

    passed, prose_chars, prose_ratio = _gate_enriched_content(note, raw_text)
    # Ratio check is disabled — content passes on prose chars alone
    assert passed is True
    assert prose_chars >= 300  # passes hard minimum
    assert prose_ratio < 0.20  # ratio is low but gate is disabled


def test_gate_enriched_content_accepts_valid_content():
    """Valid enriched content with >= 300 prose chars and ratio >= 20%% passes."""
    from pipeline import _gate_enriched_content

    note = {
        "summary": (
            "This is a detailed summary that contains multiple sentences. "
            "It provides substantial information about the topic at hand. "
            "The content is meaningful and contains proper prose with normal words. "
            "The topic is important for understanding the broader context."
        ),
        "key_facts": [
            "First key fact is important and informative for the discussion.",
            "Second key fact adds more detail and clarifies the main points.",
            "Third key fact explains why this matters in the broader context.",
        ],
    }
    raw_text = "Some raw extracted text. " * 50  # enough chars for ratio check

    passed, prose_chars, prose_ratio = _gate_enriched_content(note, raw_text)
    assert passed is True
    assert prose_chars >= 300
    assert prose_ratio >= 0.20


def test_gate_enriched_content_rejects_video_with_timestamp_heavy_transcript():
    """Video content where raw_text has fewer than 5 real words (only timestamps) is rejected."""
    from pipeline import _gate_enriched_content

    note = {
        "summary": "Interesting content.",
        "key_facts": ["A fact."],
        "type": "video",
    }
    # Transcript that's just timestamps and symbols — no real words
    raw_text = (
        "00:00:00 --> 00:00:01\n[music playing]\n"
        "00:00:01 --> 00:00:02\n[silence]\n"
        "00:00:02 --> 00:00:03\n[applause]\n"
    )

    passed, prose_chars, prose_ratio = _gate_enriched_content(note, raw_text)
    assert passed is False


def test_gate_enriched_content_video_with_real_words_passes():
    """Video with real words in transcript (>= 5 words with alpha chars) passes gate."""
    from pipeline import _gate_enriched_content

    note = {
        "summary": "Detailed summary about machine learning concepts and their applications in modern AI systems and practical deployments.",
        "key_facts": [
            "ML is a key technology in artificial intelligence and data science.",
            "Neural networks are important for deep learning and pattern recognition.",
            "These technologies are transforming many industries worldwide.",
        ],
        "type": "video",
    }
    raw_text = (
        "00:00:00 Today we discuss machine learning and artificial intelligence. "
        "00:00:15 Neural networks form the foundation of deep learning systems. "
        "00:00:30 These technologies are transforming many industries."
    )

    passed, prose_chars, prose_ratio = _gate_enriched_content(note, raw_text)
    assert passed is True
    assert prose_chars >= 300
