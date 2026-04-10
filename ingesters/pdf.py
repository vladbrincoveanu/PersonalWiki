from docling.document_converter import DocumentConverter

_LOW_QUALITY_THRESHOLD = 200  # characters

def extract_pdf(pdf_path: str, return_quality: bool = False) -> str | tuple[str, bool]:
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    markdown = result.document.export_to_markdown()

    if not markdown:
        raise ValueError(f"No text extracted from PDF: {pdf_path}")

    low_quality = len(markdown.strip()) < _LOW_QUALITY_THRESHOLD

    if return_quality:
        return markdown, low_quality
    return markdown
