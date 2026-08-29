# tests/test_integration.py
"""Integration test: full PDF → extraction → images saved to Obsidian vault.

Mocked: pipeline.enrich, pipeline.get_store, pipeline.embed (external dependencies)
Real:   extract_pdf_full, write_note, _save_images, _replace_image_placeholders
"""
import io
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pdf_with_embedded_image() -> bytes:
    """Build a minimal PDF containing a JPEG image using raw PDF structures.

    Docling's picture extraction requires a real XObject image in the PDF.
    This is tested to produce exactly 1 picture with ``generate_picture_images=True``.
    """
    # Create a small RGB image (100×100) so docling recognises it as a figure
    img = Image.new("RGB", (100, 100), color=(200, 100, 50))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 80, 80], fill=(50, 100, 200))
    draw.ellipse([30, 30, 70, 70], fill=(255, 200, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    jpeg_bytes = buf.getvalue()

    # Assemble a minimal valid PDF with one page that renders the image
    objects: dict[int, bytes] = {}

    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    objects[3] = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /XObject << /Im1 5 0 R >> >> >>"
    )

    content = b"q 200 0 0 200 206 396 cm /Im1 Do Q"
    objects[4] = b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"

    img_header = (
        b"<< /Type /XObject /Subtype /Image /Width 100 /Height 100 "
        b"/ColorSpace /DeviceRGB /BitsPerComponent 8 "
        b"/Filter /DCTDecode /Length " + str(len(jpeg_bytes)).encode() + b" >>\n"
        b"stream\n"
    )
    objects[5] = img_header + jpeg_bytes + b"\nendstream"

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}

    for obj_num in sorted(objects):
        offsets[obj_num] = out.tell()
        out.write(str(obj_num).encode() + b" 0 obj\n")
        out.write(objects[obj_num])
        out.write(b"\nendobj\n")

    xref_pos = out.tell()
    out.write(b"xref\n")
    out.write(b"0 " + str(len(objects) + 1).encode() + b"\n")
    out.write(b"0000000000 65535 f \n")
    for obj_num in sorted(offsets):
        out.write(str(offsets[obj_num]).zfill(10).encode() + b" 00000 n \n")

    out.write(
        b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF\n"
    )
    return out.getvalue()


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_pdf_with_image_creates_note_and_saves_figures():
    """End-to-end: PDF with figure → extraction → PNG saved → note written."""
    from pipeline import run_pipeline

    # -- Setup mocks for external dependencies --------------------------------
    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    def fake_enrich(raw_text, similar_titles, source):
        """Return a minimal structured note, preserving the real raw_text so
        that write_note can replace <!-- image --> placeholders."""
        substantial_summary = (
            "This integration test validates that PDF documents with embedded figures "
            "are correctly processed through the pipeline. The extraction captures both "
            "textual content and visual elements, preserving the document structure."
        )
        return {
            "title": "Integration Test Figure",
            "type": "paper",
            "tags": ["test", "integration"],
            "summary": substantial_summary,
            "key_facts": [
                "The PDF extraction process successfully captured the document content.",
                "Figure extraction generated PNG images from embedded visual elements.",
                "The note writer correctly replaced image placeholders with Obsidian links.",
            ],
            "cross_links": [],
            "raw_text": raw_text,  # pass through real extracted markdown
            "error": False,
        }

    def fake_enrich_with_images(raw_text, similar_titles, source, images):
        return fake_enrich(raw_text, similar_titles, source)

    # -- Create temp PDF on disk ----------------------------------------------
    pdf_bytes = _make_pdf_with_embedded_image()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir(parents=True)

        pdf_path = tmp_path / "test_figure.pdf"
        pdf_path.write_bytes(pdf_bytes)

        # -- Wire up patches --------------------------------------------------
        # Bypass QualityGate which rejects thin PDFs (this test is about image saving, not content quality)
        mock_gate_result = MagicMock(pass_=True, reason="")

        with (
            patch("pipeline.get_store", return_value=mock_store),
            patch("pipeline.embed", return_value=[0.0] * 384),
            patch("pipeline.enrich", side_effect=fake_enrich),
            patch("pipeline.enrich_with_images", side_effect=fake_enrich_with_images),
            patch("core.quality_gate.QualityGate") as mock_gate_cls,
            patch("vault.writer.VAULT_PATH", tmp_path),
            patch("vault.writer.NOTES_DIR", notes_dir),
        ):
            mock_gate_cls.return_value.check.return_value = mock_gate_result
            messages = []
            async for msg in run_pipeline(pdf_path=str(pdf_path)):
                messages.append(msg)

        # -- Pipeline should have completed without error ---------------------
        assert not any("Error" in m for m in messages), (
            f"Pipeline emitted an error: {messages}"
        )
        assert any("Saved" in m for m in messages), (
            f"Pipeline never reported 'Saved': {messages}"
        )

        # -- Note file must exist ---------------------------------------------
        note_slug = "integration-test-figure"
        note_file = notes_dir / f"{note_slug}.md"
        assert note_file.exists(), (
            f"Expected note file at {note_file}. "
            f"notes_dir contents: {list(notes_dir.iterdir())}"
        )

        # -- Note frontmatter must be correct ---------------------------------
        import frontmatter
        post = frontmatter.load(str(note_file))
        assert post.metadata["title"] == "Integration Test Figure"
        assert post.metadata["source"] == str(pdf_path)

        # -- At least one PNG must be saved to the attachments dir ------------
        attachments_dir = tmp_path / "attachments" / note_slug
        assert attachments_dir.exists(), (
            f"Expected attachments dir at {attachments_dir}."
        )
        figure_1 = attachments_dir / "figure-1.png"
        assert figure_1.exists(), (
            f"Expected figure-1.png at {figure_1}. "
            f"Attachments dir contents: {list(attachments_dir.iterdir())}"
        )
        assert figure_1.stat().st_size > 0, "figure-1.png is empty"

        # -- Note body must use Obsidian link syntax, not raw placeholder ------
        body = post.content
        assert "<!-- image -->" not in body, (
            "Placeholder '<!-- image -->' was not replaced in the note body."
        )
        assert "![[attachments/" in body, (
            f"Expected Obsidian image link in note body. Body:\n{body[:500]}"
        )


# ---------------------------------------------------------------------------
# DOCX integration test
# ---------------------------------------------------------------------------

def _make_docx(paragraphs: list[str]) -> bytes:
    """Build a minimal DOCX file from a list of paragraph texts."""
    from docx import Document
    from docx.shared import Pt
    import io

    doc = Document()
    for text in paragraphs:
        p = doc.add_paragraph(text)
        p.runs[0].font.size = Pt(12)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_pipeline_docx_creates_note():
    """End-to-end: DOCX file → extraction → note written to vault."""
    from pipeline import run_pipeline

    # -- Setup mocks for external dependencies --------------------------------
    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    def fake_enrich(raw_text, similar_titles, source):
        return {
            "title": "Test DOCX Note",
            "type": "document",
            "tags": ["test", "docx"],
            "summary": (
                "This is a detailed summary of the test DOCX note created by the integration test suite. "
                "It contains enough characters to pass the prose gate requirement of 300 or more characters. "
                "The summary describes the purpose and outcome of the DOCX ingestion pipeline test."
            ),
            "key_facts": [
                "DOCX extraction worked correctly and extracted all paragraphs.",
                "Pipeline completed successfully without errors.",
                "Note was written to the vault with correct frontmatter.",
            ],
            "cross_links": [],
            "raw_text": raw_text,
            "error": False,
        }

    # -- Create temp DOCX ---------------------------------------------------
    docx_bytes = _make_docx([
        "Integration Test Document",
        "This is the first paragraph of the test DOCX file.",
        "Second paragraph with more content to exceed quality gate thresholds.",
        "Third paragraph ensuring we have enough content for prose quality checks.",
        "Fourth paragraph adding more text to push the total character count above the 500 character minimum threshold.",
        "Fifth paragraph with additional content that helps ensure the DOCX file passes the quality gate checks.",
        "Sixth paragraph making this document sufficiently long enough to pass all quality and content length validations.",
    ])

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir(parents=True)

        docx_path = tmp_path / "test_docx_integration.docx"
        docx_path.write_bytes(docx_bytes)

        with (
            patch("pipeline.get_store", return_value=mock_store),
            patch("pipeline.embed", return_value=[0.0] * 384),
            patch("pipeline.enrich", side_effect=fake_enrich),
            patch("vault.writer.VAULT_PATH", tmp_path),
            patch("vault.writer.NOTES_DIR", notes_dir),
        ):
            messages = []
            async for msg in run_pipeline(docx_path=str(docx_path)):
                messages.append(msg)

        # -- Pipeline should have completed without error ---------------------
        assert not any("Error" in m for m in messages), (
            f"Pipeline emitted an error: {messages}"
        )
        assert any("Saved" in m for m in messages), (
            f"Pipeline never reported 'Saved': {messages}"
        )
        assert any("Extracting content" in m for m in messages), (
            f"Pipeline never reported 'Extracting content': {messages}"
        )

        # -- Note file must exist ---------------------------------------------
        note_file = notes_dir / "test-docx-note.md"
        assert note_file.exists(), (
            f"Expected note file at {note_file}. "
            f"notes_dir contents: {list(notes_dir.iterdir())}"
        )

        # -- Note frontmatter must be correct ---------------------------------
        import frontmatter
        post = frontmatter.load(str(note_file))
        assert post.metadata["title"] == "Test DOCX Note"
        assert post.metadata["source"] == str(docx_path)
        assert post.metadata["type"] == "document"

        # -- Note body must contain extracted text ---------------------------
        assert "Integration Test Document" in post.content
        assert "first paragraph" in post.content
