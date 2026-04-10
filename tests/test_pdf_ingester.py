import pytest
from unittest.mock import patch, MagicMock
from ingesters.pdf import extract_pdf

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
