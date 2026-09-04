import io

import pymupdf
import pytest
from PIL import Image

from ingesters.pdf import PdfExtractResult, extract_pdf, extract_pdf_full


def _save_pdf(tmp_path, name, draw_page):
    path = tmp_path / name
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    draw_page(page)
    document.save(path)
    document.close()
    return path


def _png_bytes(color):
    image = Image.new("RGB", (160, 100), color=color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_extract_pdf_preserves_generated_text(tmp_path):
    expected = "Generated PDF text remains searchable and useful."
    path = _save_pdf(
        tmp_path,
        "generated.pdf",
        lambda page: page.insert_text((72, 100), expected, fontsize=16),
    )

    markdown = extract_pdf(str(path))

    assert isinstance(markdown, str)
    assert expected in markdown


def test_extract_pdf_preserves_multi_column_reading_order(tmp_path):
    def draw(page):
        page.insert_text((50, 80), "LEFT COLUMN ALPHA", fontsize=16)
        page.insert_text((50, 115), "Left-side detail follows alpha.", fontsize=12)
        page.insert_text((330, 80), "RIGHT COLUMN OMEGA", fontsize=16)
        page.insert_text((330, 115), "Right-side detail follows omega.", fontsize=12)

    path = _save_pdf(tmp_path, "columns.pdf", draw)

    markdown = extract_pdf(str(path))

    assert "LEFT COLUMN ALPHA" in markdown
    assert "RIGHT COLUMN OMEGA" in markdown
    assert markdown.index("LEFT COLUMN ALPHA") < markdown.index("RIGHT COLUMN OMEGA")


def test_extract_pdf_preserves_table_content(tmp_path):
    def draw(page):
        x_positions = (72, 250, 430)
        y_positions = (100, 145, 190)
        for x in x_positions:
            page.draw_line((x, y_positions[0]), (x, y_positions[-1]))
        for y in y_positions:
            page.draw_line((x_positions[0], y), (x_positions[-1], y))
        page.insert_text((85, 130), "Project", fontsize=12)
        page.insert_text((270, 130), "Owner", fontsize=12)
        page.insert_text((85, 175), "Apollo", fontsize=12)
        page.insert_text((270, 175), "Mira", fontsize=12)

    path = _save_pdf(tmp_path, "table.pdf", draw)

    markdown = extract_pdf(str(path))

    assert "Project" in markdown
    assert "Owner" in markdown
    assert "Apollo" in markdown
    assert "Mira" in markdown


def test_extract_pdf_uses_english_ocr_for_rasterized_scan(tmp_path):
    source = pymupdf.open()
    source_page = source.new_page(width=900, height=300)
    source_page.insert_text(
        (50, 170),
        "ZEBRA ORBIT 7429",
        fontsize=48,
        fontname="hebo",
    )
    raster = source_page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes("png")
    source.close()

    path = _save_pdf(
        tmp_path,
        "scan.pdf",
        lambda page: page.insert_image(page.rect, stream=raster),
    )

    markdown = extract_pdf(str(path))

    normalized = " ".join(markdown.upper().split())
    assert "ZEBRA ORBIT 7429" in normalized


def test_extract_pdf_full_returns_images_in_markdown_order(tmp_path):
    red = _png_bytes((240, 20, 20))
    blue = _png_bytes((20, 20, 240))

    def draw(page):
        page.insert_text((72, 60), "Ordered figures", fontsize=16)
        page.insert_image(pymupdf.Rect(72, 90, 232, 190), stream=red)
        page.insert_text((72, 220), "Between the figures", fontsize=12)
        page.insert_image(pymupdf.Rect(72, 250, 232, 350), stream=blue)
        page.insert_text((72, 390), "End of ordered figures", fontsize=12)

    path = _save_pdf(tmp_path, "images.pdf", draw)

    result = extract_pdf_full(str(path))

    assert isinstance(result, PdfExtractResult)
    assert result.markdown.count("<!-- image -->") == 2
    assert "![" not in result.markdown
    assert len(result.images) == 2
    first = Image.open(io.BytesIO(result.images[0])).convert("RGB").resize((1, 1)).getpixel((0, 0))
    second = Image.open(io.BytesIO(result.images[1])).convert("RGB").resize((1, 1)).getpixel((0, 0))
    assert first[0] > first[2]
    assert second[2] > second[0]


def test_extract_pdf_full_without_images_returns_empty_image_list(tmp_path):
    path = _save_pdf(
        tmp_path,
        "text-only.pdf",
        lambda page: page.insert_textbox(
            pymupdf.Rect(72, 72, 540, 500),
            "Text only document " * 20,
            fontsize=12,
        ),
    )

    result = extract_pdf_full(str(path))

    assert result.images == []


def test_extract_pdf_flags_short_text_as_low_quality(tmp_path):
    path = _save_pdf(
        tmp_path,
        "short.pdf",
        lambda page: page.insert_text((72, 100), "Short PDF", fontsize=12),
    )

    markdown, low_quality = extract_pdf(str(path), return_quality=True)

    assert "Short PDF" in markdown
    assert low_quality is True


def test_extract_pdf_does_not_flag_useful_long_text_as_low_quality(tmp_path):
    text = "Useful generated content remains available for downstream enrichment. " * 8
    path = _save_pdf(
        tmp_path,
        "long.pdf",
        lambda page: page.insert_textbox(pymupdf.Rect(72, 72, 540, 500), text, fontsize=12),
    )

    _, low_quality = extract_pdf(str(path), return_quality=True)

    assert low_quality is False


def test_extract_pdf_raises_for_empty_pdf(tmp_path):
    path = _save_pdf(tmp_path, "empty.pdf", lambda page: None)

    with pytest.raises(ValueError, match="No text extracted"):
        extract_pdf(str(path))


def test_extract_pdf_raises_for_invalid_pdf(tmp_path):
    path = tmp_path / "invalid.pdf"
    path.write_bytes(b"not a pdf")

    with pytest.raises(Exception):
        extract_pdf(str(path))
