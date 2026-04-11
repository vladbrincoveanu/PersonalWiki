# PDF Image Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract figures from PDFs and embed them as real Obsidian image links at the `<!-- image -->` placeholder locations.

**Architecture:** Docling's `generate_picture_images` option extracts per-figure PNG bytes in document order, parallel to the `<!-- image -->` placeholders in the markdown output. The pipeline passes these bytes to the vault writer, which saves them to `attachments/<slug>/` and rewrites the placeholders before writing the note.

**Tech Stack:** docling (`PdfPipelineOptions`, `PdfFormatOption`), Pillow (PIL, via docling), Python `io.BytesIO`, Python-frontmatter

---

## File Map

| File | Change |
|------|--------|
| `ingesters/pdf.py` | Add `PdfExtractResult` dataclass + `extract_pdf_full()` |
| `pipeline.py` | Call `extract_pdf_full()` for PDF paths; pass `images` to `write_note()` |
| `vault/writer.py` | Add `images` param; save PNGs; replace `<!-- image -->` placeholders |
| `tests/test_pdf_ingester.py` | Add tests for `extract_pdf_full` |
| `tests/test_writer.py` | Add tests for image saving + placeholder replacement |
| `tests/test_pipeline.py` | Update mock for `extract_pdf_full`; assert images threaded through |

---

### Task 1: `PdfExtractResult` dataclass + `extract_pdf_full()` in `ingesters/pdf.py`

**Files:**
- Modify: `ingesters/pdf.py`
- Test: `tests/test_pdf_ingester.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pdf_ingester.py`:

```python
import io
from unittest.mock import patch, MagicMock
from ingesters.pdf import extract_pdf_full, PdfExtractResult

def _make_mock_picture(png_bytes: bytes):
    """Return a mock docling picture with a pil_image that saves to png_bytes."""
    from unittest.mock import MagicMock
    import io
    from PIL import Image
    # Create a real 1x1 PNG so save() works
    real_img = Image.new("RGB", (1, 1), color=(255, 0, 0))
    mock_picture = MagicMock()
    mock_picture.image.pil_image = real_img
    return mock_picture

def test_extract_pdf_full_returns_dataclass():
    mock_doc = MagicMock()
    mock_doc.export_to_markdown.return_value = "# Title\n\nText <!-- image --> more text."
    mock_doc.pictures = [_make_mock_picture(b"fakepng")]
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_pdf_ingester.py::test_extract_pdf_full_returns_dataclass tests/test_pdf_ingester.py::test_extract_pdf_full_no_images tests/test_pdf_ingester.py::test_extract_pdf_full_skips_picture_with_no_image -v
```

Expected: FAIL with `ImportError: cannot import name 'extract_pdf_full'`

- [ ] **Step 3: Implement `PdfExtractResult` and `extract_pdf_full` in `ingesters/pdf.py`**

Replace the full file:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_pdf_ingester.py -v
```

Expected: All pass (including pre-existing tests for `extract_pdf`)

- [ ] **Step 5: Commit**

```bash
git add ingesters/pdf.py tests/test_pdf_ingester.py
git commit -m "feat: add extract_pdf_full with per-figure image extraction"
```

---

### Task 2: Image saving + placeholder replacement in `vault/writer.py`

**Files:**
- Modify: `vault/writer.py`
- Test: `tests/test_writer.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_writer.py`:

```python
import re
from pathlib import Path

def test_write_note_saves_images_and_replaces_placeholders():
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Intro <!-- image --> middle <!-- image --> end.",
        "error": False,
    }
    # Minimal valid 1x1 PNG bytes
    import struct, zlib
    def minimal_png():
        sig = b'\x89PNG\r\n\x1a\n'
        ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data)
        ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
        raw = b'\x00\xff\x00\x00'  # filter byte + 1 RGB pixel
        compressed = zlib.compress(raw)
        idat_crc = zlib.crc32(b'IDAT' + compressed)
        idat = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc)
        iend_crc = zlib.crc32(b'IEND')
        iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
        return sig + ihdr + idat + iend

    fake_png = minimal_png()
    images = [fake_png, fake_png]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()

        with patch("vault.writer.NOTES_DIR", notes_dir), \
             patch("vault.writer.VAULT_PATH", tmp_path):
            path = write_note(note, source="https://example.com/paper.pdf", images=images)

        post = frontmatter.load(path)
        body = post.content

        # Both placeholders replaced
        assert "<!-- image -->" not in body
        assert "![[attachments/test-paper/figure-1.png]]" in body
        assert "![[attachments/test-paper/figure-2.png]]" in body

        # Image files exist
        assert (tmp_path / "attachments" / "test-paper" / "figure-1.png").exists()
        assert (tmp_path / "attachments" / "test-paper" / "figure-2.png").exists()

def test_write_note_no_images_unchanged():
    """write_note without images keeps <!-- image --> as-is and creates no attachments dir."""
    note = {
        "title": "Web Article",
        "type": "article",
        "tags": [],
        "summary": "Summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some text <!-- image --> here.",
        "error": False,
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()

        with patch("vault.writer.NOTES_DIR", notes_dir), \
             patch("vault.writer.VAULT_PATH", tmp_path):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        assert "<!-- image -->" in post.content
        assert not (tmp_path / "attachments").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_writer.py::test_write_note_saves_images_and_replaces_placeholders tests/test_writer.py::test_write_note_no_images_unchanged -v
```

Expected: FAIL with `TypeError` (unexpected keyword argument `images`)

- [ ] **Step 3: Implement image saving in `vault/writer.py`**

Replace the full file:

```python
import re
from datetime import date
from pathlib import Path
import frontmatter
from config import NOTES_DIR, VAULT_PATH


def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug


def _save_images(images: list[bytes], slug: str) -> None:
    images_dir = VAULT_PATH / "attachments" / slug
    images_dir.mkdir(parents=True, exist_ok=True)
    for i, png_bytes in enumerate(images, start=1):
        (images_dir / f"figure-{i}.png").write_bytes(png_bytes)


def _replace_image_placeholders(text: str, slug: str, count: int) -> str:
    result = text
    for i in range(1, count + 1):
        result = result.replace(
            "<!-- image -->",
            f"![[attachments/{slug}/figure-{i}.png]]",
            1,
        )
    return result


def write_note(
    note: dict,
    source: str,
    ingested_date: str | None = None,
    images: list[bytes] = (),
) -> str:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    title = note.get("title") or "Untitled"
    ingested_date = ingested_date or str(date.today())
    slug = slugify(title)
    filepath = NOTES_DIR / f"{slug}.md"

    # Handle slug collisions
    counter = 1
    while filepath.exists():
        filepath = NOTES_DIR / f"{slug}-{counter}.md"
        counter += 1
    # Use the final slug (with counter if collided) for image directory
    final_slug = filepath.stem

    metadata = {
        "title": title,
        "source": source,
        "type": note.get("type", "article"),
        "tags": note.get("tags", []),
        "ingested": ingested_date,
    }
    if note.get("error"):
        metadata["confidence"] = "low"

    cross_links = note.get("cross_links", [])
    cross_links_section = ""
    if cross_links:
        links_str = ", ".join(f"[[{l}]]" for l in cross_links)
        cross_links_section = f"\n## My Knowledge Says\n{links_str}\n"

    key_facts = note.get("key_facts", [])
    facts_str = "\n".join(f"- {f}" for f in key_facts) if key_facts else "_None extracted._"

    raw_text = note.get("raw_text", "")
    if images:
        _save_images(images, final_slug)
        raw_text = _replace_image_placeholders(raw_text, final_slug, len(images))

    raw_section = f"\n## Raw Extract\n<details>\n<summary>Original extracted text</summary>\n\n{raw_text}\n\n</details>"

    body = f"""## Summary
{note.get('summary', '_Not available._')}

## Key Facts
{facts_str}
{cross_links_section}{raw_section}"""

    post = frontmatter.Post(body, **metadata)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))

    return str(filepath)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_writer.py -v
```

Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add vault/writer.py tests/test_writer.py
git commit -m "feat: save PDF figures to attachments and rewrite image placeholders"
```

---

### Task 3: Wire `extract_pdf_full` through `pipeline.py`

**Files:**
- Modify: `pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_pipeline_pdf_url_passes_images_to_writer():
    from pipeline import run_pipeline
    from ingesters.pdf import PdfExtractResult

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    fake_result = PdfExtractResult(
        markdown="# Paper\n\n<!-- image --> some content " + "x" * 300,
        low_quality=False,
        images=[b"fakepng1", b"fakepng2"],
    )

    written_images = []

    def capture_write_note(note, source, images=()):
        written_images.extend(images)
        return "/vault/notes/paper.md"

    with patch("pipeline.get_store", return_value=mock_store), \
         patch("pipeline._is_pdf_url", return_value=True), \
         patch("pipeline.extract_pdf_full", return_value=fake_result), \
         patch("pipeline.embed", return_value=[0.1] * 384), \
         patch("pipeline.enrich", return_value={
             "title": "Paper", "type": "paper", "tags": [],
             "summary": "S.", "key_facts": [], "cross_links": [],
             "raw_text": "raw", "error": False,
         }), \
         patch("pipeline.write_note", side_effect=capture_write_note), \
         patch("asyncio.to_thread", new_callable=MagicMock) as mock_to_thread:

        # Make asyncio.to_thread return the fake_result for extract_pdf_full
        # and delegate normally for enrich (synchronous mock above handles it)
        async def fake_to_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)
        mock_to_thread.side_effect = fake_to_thread

        messages = []
        async for msg in run_pipeline(url="https://arxiv.org/pdf/2510.18518"):
            messages.append(msg)

    assert written_images == [b"fakepng1", b"fakepng2"]
    assert any("Saved" in m for m in messages)
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_pipeline.py::test_pipeline_pdf_url_passes_images_to_writer -v
```

Expected: FAIL with `ImportError` or assertion error (images not passed)

- [ ] **Step 3: Update `pipeline.py`**

Replace the relevant import and PDF extraction calls:

```python
import asyncio
import os
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from typing import AsyncGenerator
from config import TOP_K_SIMILAR, MAX_EMBED_CHARS
from core.embeddings import embed
from core.vector_store import get_store
from core.minimax_client import enrich
from ingesters.web import extract_url
from ingesters.pdf import extract_pdf, extract_pdf_full
from vault.writer import write_note


def _is_pdf_url(url: str) -> bool:
    """Return True if the URL serves a PDF (by extension or Content-Type)."""
    if url.lower().split("?")[0].endswith(".pdf"):
        return True
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as resp:
            ct = resp.headers.get("Content-Type", "")
            return "application/pdf" in ct
    except Exception:
        return False


async def run_pipeline(
    url: str | None = None,
    pdf_path: str | None = None,
) -> AsyncGenerator[str, None]:
    store = get_store()
    source = url or pdf_path

    # Duplicate check
    if url and store.exists(url):
        yield "Warning: Note for this URL already exists. Skipping."
        return

    # Step 1: Extract
    yield "Extracting content..."
    tmp_pdf_path = None
    images: list[bytes] = []
    try:
        if url and _is_pdf_url(url):
            yield "Detected PDF URL — downloading..."
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_pdf_path = tmp.name
            await asyncio.to_thread(urllib.request.urlretrieve, url, tmp_pdf_path)
            result = await asyncio.to_thread(extract_pdf_full, tmp_pdf_path)
            raw_text = result.markdown
            images = result.images
        elif url:
            raw_text = await extract_url(url)
        else:
            result = await asyncio.to_thread(extract_pdf_full, pdf_path)
            raw_text = result.markdown
            images = result.images
    except Exception as e:
        yield f"Error during extraction: {e}"
        return
    finally:
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            os.unlink(tmp_pdf_path)

    # Step 2: Find similar
    yield "Finding similar notes..."
    vector = embed(raw_text[:MAX_EMBED_CHARS])
    similar = store.search(vector, top_k=TOP_K_SIMILAR)
    similar_titles = [
        s["metadata"].get("title", Path(s["path"]).stem)
        for s in similar
        if isinstance(s.get("metadata"), dict)
    ]
    yield f"Finding similar notes ({len(similar)} found)..."

    # Step 3: Enrich
    yield "Enriching with Minimax..."
    note = await asyncio.to_thread(enrich, raw_text, similar_titles, source)

    # Step 4: Write
    yield "Saving note..."
    path = write_note(note, source=source, images=images)

    # Step 5: Index
    yield "Indexing..."
    index_meta = {k: v for k, v in note.items() if k != "raw_text"}
    index_meta["_file_path"] = path
    store.upsert(
        path=source,
        text=raw_text,
        vector=vector,
        links=note.get("cross_links", []),
        metadata=index_meta,
    )

    stem = Path(path).name
    yield f"Saved -> notes/{stem}"
```

- [ ] **Step 4: Run all tests**

```
pytest tests/ -v
```

Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "feat: wire extract_pdf_full images through pipeline to vault writer"
```

---

## Self-Review

**Spec coverage:**
- `ingesters/pdf.py` — `PdfExtractResult` dataclass + `extract_pdf_full` ✓
- `pipeline.py` — uses `extract_pdf_full`, passes `images` to `write_note` ✓
- `vault/writer.py` — saves PNGs to `attachments/<slug>/`, replaces placeholders ✓
- Edge case: 0 images — tested (`test_extract_pdf_full_no_images`, `test_write_note_no_images_unchanged`) ✓
- Edge case: picture with `None` image — tested (`test_extract_pdf_full_skips_picture_with_no_image`) ✓
- Backward compat: `extract_pdf()` unchanged, existing tests unaffected ✓

**Placeholder scan:** No TBDs, all steps have complete code.

**Type consistency:**
- `PdfExtractResult.images: list[bytes]` — used consistently in Task 1, 2, 3
- `write_note(..., images: list[bytes] = ())` — matches usage in Task 3
- `extract_pdf_full` imported in Task 3 matches definition in Task 1
- `_save_images(images, final_slug)` and `_replace_image_placeholders(raw_text, final_slug, len(images))` — all defined in Task 2 body
