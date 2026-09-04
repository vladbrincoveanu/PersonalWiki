import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
import pymupdf4llm

_LOW_QUALITY_THRESHOLD = 200
_IMAGE_LINK = re.compile(
    r"!\[(?:\\.|[^\]\\])*\]\(\s*"
    r"(?:<(?P<angle>[^>\n]+)>|(?P<plain>(?:\\.|[^)\s])+))"
    r"(?:\s+(?:\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|\((?:\\.|[^)])*\)))?"
    r"\s*\)"
)


@dataclass
class PdfExtractResult:
    markdown: str
    low_quality: bool
    images: list[bytes] = field(default_factory=list)


def _preflight_pdf(pdf_path: str) -> None:
    try:
        with pymupdf.open(pdf_path) as document:
            if document.needs_pass or document.page_count == 0:
                raise ValueError(f"Failed to extract PDF: {pdf_path}")
    except pymupdf.FileDataError as exc:
        raise ValueError(f"Failed to extract PDF: {pdf_path}") from exc


def _to_markdown(pdf_path: str, **kwargs) -> str:
    _preflight_pdf(pdf_path)
    try:
        return pymupdf4llm.to_markdown(
            pdf_path,
            use_ocr=True,
            ocr_language="eng",
            **kwargs,
        )
    except pymupdf.FileDataError as exc:
        raise ValueError(f"Failed to extract PDF: {pdf_path}") from exc


def extract_pdf(pdf_path: str, return_quality: bool = False) -> str | tuple[str, bool]:
    markdown = _to_markdown(pdf_path)
    if not markdown.strip():
        raise ValueError(f"No text extracted from PDF: {pdf_path}")

    low_quality = len(markdown.strip()) < _LOW_QUALITY_THRESHOLD
    if return_quality:
        return markdown, low_quality
    return markdown


def extract_pdf_full(pdf_path: str) -> PdfExtractResult:
    """Extract PDF text and image bytes in markdown order."""
    with tempfile.TemporaryDirectory() as image_dir:
        markdown = _to_markdown(
            pdf_path,
            write_images=True,
            image_path=image_dir,
            image_format="png",
        )
        if not markdown.strip():
            raise ValueError(f"No text extracted from PDF: {pdf_path}")

        image_root = Path(image_dir).resolve()
        images: list[bytes] = []

        def collect_image(match: re.Match) -> str:
            raw_path = match.group("angle") or match.group("plain")
            try:
                image_path = Path(raw_path.replace(r"\ ", " ")).resolve()
                if not image_path.is_relative_to(image_root):
                    return match.group(0)
                image_bytes = image_path.read_bytes()
            except (OSError, ValueError):
                return match.group(0)
            images.append(image_bytes)
            return "<!-- image -->"

        markdown = _IMAGE_LINK.sub(collect_image, markdown)

    return PdfExtractResult(
        markdown=markdown,
        low_quality=len(markdown.strip()) < _LOW_QUALITY_THRESHOLD,
        images=images,
    )
