import io
import pytest
from unittest.mock import patch, MagicMock
from ingesters.pdf import extract_pdf, extract_pdf_full, PdfExtractResult

def test_extract_pdf_returns_markdown():
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = "# Title\n\nSome content from the PDF."
    mock_result = MagicMock()
    mock_result.document = mock_doc

    with patch("ingesters.pdf.DocumentConverter") as MockConverter:
        instance = MagicMock()
        instance.convert.return_value = mock_result
        MockConverter.return_value = instance

        result = extract_pdf("/path/to/paper.pdf")

    assert "Title" in result
    assert "Some content from the PDF." in result

def test_extract_pdf_raises_on_empty():
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = ""
    mock_result = MagicMock()
    mock_result.document = mock_doc

    with patch("ingesters.pdf.DocumentConverter") as MockConverter:
        instance = MagicMock()
        instance.convert.return_value = mock_result
        MockConverter.return_value = instance

        with pytest.raises(ValueError, match="No text extracted"):
            extract_pdf("/path/to/empty.pdf")

def test_extract_pdf_flags_low_quality():
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = "Page 1"
    mock_result = MagicMock()
    mock_result.document = mock_doc

    with patch("ingesters.pdf.DocumentConverter") as MockConverter:
        instance = MagicMock()
        instance.convert.return_value = mock_result
        MockConverter.return_value = instance

        result, low_quality = extract_pdf("/path/to/scan.pdf", return_quality=True)

    assert low_quality is True


def _make_mock_picture():
    """Return a mock docling picture with a pil_image that saves to png_bytes."""
    from PIL import Image
    # Create a real 1x1 PNG so save() works
    real_img = Image.new("RGB", (1, 1), color=(255, 0, 0))
    mock_picture = MagicMock()
    mock_picture.image.pil_image = real_img
    return mock_picture

def test_extract_pdf_full_returns_dataclass():
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = "# Title\n\nText <!-- image --> more text. " + "x" * 300
    mock_doc.pictures = [_make_mock_picture()]
    mock_result = MagicMock()
    mock_result.document = mock_doc

    with patch("ingesters.pdf.DocumentConverter") as MockConverter, \
         patch("ingesters.pdf.PdfFormatOption"), \
         patch("ingesters.pdf.PdfPipelineOptions"):
        instance = MagicMock()
        instance.convert.return_value = mock_result
        MockConverter.return_value = instance

        result = extract_pdf_full("/path/to/paper.pdf")

    assert isinstance(result, PdfExtractResult)
    assert "Title" in result.markdown
    assert len(result.images) == 1
    assert isinstance(result.images[0], bytes)
    assert result.low_quality is False

def test_extract_pdf_full_no_images():
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = "# Title\n\n" + "x" * 300
    mock_doc.pictures = []
    mock_result = MagicMock()
    mock_result.document = mock_doc

    with patch("ingesters.pdf.DocumentConverter") as MockConverter, \
         patch("ingesters.pdf.PdfFormatOption"), \
         patch("ingesters.pdf.PdfPipelineOptions"):
        instance = MagicMock()
        instance.convert.return_value = mock_result
        MockConverter.return_value = instance

        result = extract_pdf_full("/path/to/paper.pdf")

    assert isinstance(result, PdfExtractResult)
    assert result.images == []

def test_extract_pdf_full_skips_picture_with_no_image():
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = "# Title\n\n" + "x" * 300
    mock_picture = MagicMock()
    mock_picture.image = None
    mock_doc.pictures = [mock_picture]
    mock_result = MagicMock()
    mock_result.document = mock_doc

    with patch("ingesters.pdf.DocumentConverter") as MockConverter, \
         patch("ingesters.pdf.PdfFormatOption"), \
         patch("ingesters.pdf.PdfPipelineOptions"):
        instance = MagicMock()
        instance.convert.return_value = mock_result
        MockConverter.return_value = instance

        result = extract_pdf_full("/path/to/paper.pdf")

    assert result.images == []
