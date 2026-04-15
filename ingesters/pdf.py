import io
from dataclasses import dataclass, field
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat

_LOW_QUALITY_THRESHOLD = 200  # characters


@dataclass
class PdfExtractResult:
    markdown: str
    low_quality: bool
    images: list[bytes] = field(default_factory=list)


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


def extract_pdf_full(pdf_path: str) -> PdfExtractResult:
    """Extract PDF text and figures. Returns markdown + PNG bytes for each figure."""
    pipeline_opts = PdfPipelineOptions()
    pipeline_opts.generate_picture_images = True

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)
        }
    )
    result = converter.convert(pdf_path)
    markdown = result.document.export_to_markdown()

    if not markdown:
        raise ValueError(f"No text extracted from PDF: {pdf_path}")

    low_quality = len(markdown.strip()) < _LOW_QUALITY_THRESHOLD

    images: list[bytes] = []
    for picture in result.document.pictures:
        if picture.image is None:
            continue
        buf = io.BytesIO()
        picture.image.pil_image.save(buf, format="PNG")
        images.append(buf.getvalue())

    return PdfExtractResult(markdown=markdown, low_quality=low_quality, images=images)
