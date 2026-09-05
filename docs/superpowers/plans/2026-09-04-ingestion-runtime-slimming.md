# Ingestion Runtime Slimming Implementation Plan

> **For agentic workers:** Implement this plan task-by-task, verifying each task before starting the next. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the existing ingestion interface while removing Whisper, FFmpeg, Docling, sentence-transformers, Torch, CUDA, and NVIDIA runtime packages.

**Architecture:** Keep the pipeline and its extractor interfaces stable. Simplify YouTube to caption adapters, replace reranking with FastEmbed's ONNX cross-encoder, and replace PDF conversion with PyMuPDF4LLM plus best-effort image extraction and OCR. Regenerate locks from direct requirements and verify behavior locally before any deployment work.

**Tech Stack:** Python 3.13, pytest, FastEmbed/ONNX Runtime, PyMuPDF4LLM, PyMuPDF Layout, Tesseract OCR, Docker Compose.

---

## File Structure

- `ingesters/youtube.py`: caption-only YouTube extraction.
- `core/reranker.py`: stable reranking interface backed by FastEmbed.
- `ingesters/pdf.py`: stable `PdfExtractResult` interface backed by PyMuPDF4LLM.
- `requirements.txt`: direct runtime dependencies only.
- `requirements.lock.txt`: generated production transitive lock.
- `requirements-dev.lock.txt`: generated development transitive lock.
- `Dockerfile`: required build/runtime system packages and pinned Playwright installation.
- `.github/workflows/ci.yml`: OCR system dependency for deterministic PDF tests.
- `tests/test_youtube_ingester.py`: caption and no-transcript behavior.
- `tests/test_keywords_api.py`: remove the obsolete global Whisper module shim.
- `tests/test_reranker.py`: implementation-independent reranker interface tests.
- `tests/test_pdf_ingester.py`: generated representative PDF corpus and extractor contract.
- `tests/test_runtime_dependencies.py`: deterministic forbidden-dependency checks.

## Task 1: Make YouTube Caption-Only

**Files:**
- Modify: `tests/test_youtube_ingester.py`
- Modify: `tests/test_keywords_api.py`
- Modify: `ingesters/youtube.py`

- [ ] **Step 1: Replace Whisper-specific tests with a failing no-audio/no-metadata test**

Delete `test_auto_caption_tier_skips_non_english`, `test_whisper_transcription`, and `test_whisper_model_cached_not_reloaded`. Remove Whisper monkeypatches from the remaining tests. Add:

```python
def test_extract_youtube_without_captions_does_not_download_audio_or_metadata(monkeypatch):
    import ingesters.youtube as yt

    subprocess_calls = []
    monkeypatch.setattr(yt, "_try_youtube_transcript_api", lambda *args: None)
    monkeypatch.setattr(yt, "_try_subtitle_tiers", lambda *args: None)
    monkeypatch.setattr(yt.subprocess, "run", lambda command, **kwargs: subprocess_calls.append(command))

    doc = yt.extract_youtube("https://youtube.com/watch?v=abc123DEF12")

    assert doc.raw_text == "[NO_TRANSCRIPT] https://youtube.com/watch?v=abc123DEF12"
    assert subprocess_calls == []
```

Delete the `sys.modules["whisper"]` shim and its explanatory comment from `tests/test_keywords_api.py`; the application must import in a clean interpreter without Whisper installed.

- [ ] **Step 2: Run the new test and verify RED**

Run: `python -m pytest tests/test_youtube_ingester.py::test_extract_youtube_without_captions_does_not_download_audio_or_metadata -v`

Expected: FAIL because the current implementation invokes the Whisper audio fallback and/or metadata lookup.

- [ ] **Step 3: Remove local transcription and metadata fallback**

In `ingesters/youtube.py`:

- Delete `import whisper`.
- Delete `_whisper_model` and `_get_whisper_model`.
- Delete `_try_whisper_transcription`.
- Delete `_get_video_metadata`.
- End `extract_youtube` immediately after subtitle tiers with:

```python
    return Document(raw_text=f"[NO_TRANSCRIPT] {url}", content_type="video")
```

- [ ] **Step 4: Run focused YouTube tests and verify GREEN**

Run: `python -m pytest tests/test_youtube_ingester.py tests/test_pipeline_md_and_video.py tests/test_video_enrichment.py tests/test_keywords_api.py -v`

Expected: all selected tests PASS, with no import or monkeypatch reference to Whisper.

- [ ] **Step 5: Commit the YouTube slice**

```bash
git add ingesters/youtube.py tests/test_youtube_ingester.py tests/test_keywords_api.py
git commit -m "refactor: make YouTube ingestion caption-only"
```

## Task 2: Replace the Torch Reranker

**Files:**
- Modify: `tests/test_reranker.py`
- Modify: `core/reranker.py`

- [ ] **Step 1: Change the injected-model test to the FastEmbed interface**

Replace the body of `test_reranker_adds_rerank_score` with:

```python
def test_reranker_adds_rerank_score():
    from core.reranker import CrossEncoderReranker

    reranker = CrossEncoderReranker()
    results = [{"path": "notes/a.md", "text": "test content"}]
    model = MagicMock()
    model.rerank.return_value = iter([0.95])
    reranker._model = model

    reranked = reranker.rerank("test query", results)

    model.rerank.assert_called_once_with("test query", ["test content"])
    assert reranked[0]["rerank_score"] == 0.95
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_reranker.py::test_reranker_adds_rerank_score -v`

Expected: FAIL because the current implementation calls `predict(pairs)`.

- [ ] **Step 3: Swap the adapter without changing the module interface**

Replace `core/reranker.py` with:

```python
"""ONNX cross-encoder reranking for hybrid-search results."""

import logging

from fastembed.rerank.cross_encoder import TextCrossEncoder

_logger = logging.getLogger(__name__)
_MODEL_NAME = "Xenova/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    def __init__(self):
        self._model = None

    @property
    def model(self):
        if self._model is None:
            try:
                self._model = TextCrossEncoder(_MODEL_NAME, lazy_load=True, cuda=False)
            except Exception as exc:
                _logger.warning("CrossEncoder model failed to load: %s", exc)
        return self._model

    def rerank(self, query: str, results: list[dict], top_k: int = 5) -> list[dict]:
        if not results or not query or self.model is None:
            return results[:top_k]
        try:
            documents = [result.get("text", "") for result in results]
            scores = list(self.model.rerank(query, documents))
            for result, score in zip(results, scores):
                result["rerank_score"] = float(score)
            return sorted(results, key=lambda result: result["rerank_score"], reverse=True)[:top_k]
        except Exception as exc:
            _logger.warning("CrossEncoder reranking failed: %s; returning vector results", exc)
            return results[:top_k]
```

- [ ] **Step 4: Run focused reranker and integration tests**

Run: `python -m pytest tests/test_reranker.py tests/test_reranker_integration.py tests/test_vector_store.py -v`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit the reranker slice**

```bash
git add core/reranker.py tests/test_reranker.py
git commit -m "refactor: use ONNX search reranking"
```

## Task 3: Establish the PDF Quality Gate

**Files:**
- Modify: `tests/test_pdf_ingester.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add direct PDF replacement dependencies**

Replace `docling==2.123.1` in `requirements.txt` with:

```text
pymupdf4llm==1.28.2
pymupdf-layout==1.28.2
```

Install direct development requirements into the active isolated environment before running the new PDF tests.

Run:

```bash
python -m pip install pymupdf4llm==1.28.2 pymupdf-layout==1.28.2
```

Expected: installation exits 0 and `python -c "import pymupdf, pymupdf4llm"` exits 0.

- [ ] **Step 2: Replace Docling mocks with a generated representative corpus**

Keep assertions for return type, low-quality detection, empty extraction, and image bytes. Generate PDFs under `tmp_path` with PyMuPDF:

```python
import io

import pymupdf
import pytest
from PIL import Image, ImageDraw

from ingesters.pdf import PdfExtractResult, extract_pdf, extract_pdf_full


def _save_pdf(tmp_path, draw_page, name="sample.pdf"):
    path = tmp_path / name
    document = pymupdf.open()
    page = document.new_page()
    draw_page(page)
    document.save(path)
    document.close()
    return path


def test_extract_pdf_preserves_text_and_columns(tmp_path):
    def draw(page):
        page.insert_textbox((40, 40, 280, 500), "LEFT COLUMN " * 40)
        page.insert_textbox((320, 40, 560, 500), "RIGHT COLUMN " * 40)

    result = extract_pdf_full(str(_save_pdf(tmp_path, draw)))

    assert "LEFT COLUMN" in result.markdown
    assert "RIGHT COLUMN" in result.markdown
    assert result.low_quality is False


def test_extract_pdf_preserves_table_content(tmp_path):
    def draw(page):
        rows = ["Company | Price | Value", "Example | 10 | 15", "Second | 20 | 30"]
        page.insert_textbox((40, 40, 560, 300), "\n".join(rows))

    markdown = extract_pdf(str(_save_pdf(tmp_path, draw, "table.pdf")))

    assert "Company" in markdown
    assert "Example" in markdown
    assert "Second" in markdown


def test_extract_pdf_returns_image_bytes(tmp_path):
    image = Image.new("RGB", (120, 60), "white")
    ImageDraw.Draw(image).text((10, 20), "chart", fill="black")
    data = io.BytesIO()
    image.save(data, format="PNG")

    def draw(page):
        page.insert_text((40, 40), "Image-bearing report " * 20)
        page.insert_image((40, 80, 280, 200), stream=data.getvalue())

    result = extract_pdf_full(str(_save_pdf(tmp_path, draw, "image.pdf")))

    assert result.images
    assert all(isinstance(item, bytes) for item in result.images)


def test_extract_pdf_uses_ocr_for_scanned_page(tmp_path):
    source = pymupdf.open()
    source_page = source.new_page(width=1200, height=400)
    source_page.insert_text((40, 200), "SCANNED VALUE INVESTING REPORT", fontsize=48)
    scan = source_page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
    source.close()

    def draw(page):
        page.insert_image(page.rect, stream=scan)

    result = extract_pdf_full(str(_save_pdf(tmp_path, draw, "scan.pdf")))

    assert "SCANNED" in result.markdown.upper()
```

- [ ] **Step 3: Run the corpus tests and verify RED**

Run: `python -m pytest tests/test_pdf_ingester.py -v`

Expected: FAIL because `ingesters/pdf.py` still imports and mocks Docling instead of satisfying the real corpus through PyMuPDF.

## Task 4: Replace Docling Behind the Existing Interface

**Files:**
- Modify: `ingesters/pdf.py`
- Test: `tests/test_pdf_ingester.py`

- [ ] **Step 1: Implement Markdown and image extraction**

Replace `ingesters/pdf.py` with:

```python
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf4llm

_LOW_QUALITY_THRESHOLD = 200
_IMAGE_LINK = re.compile(r"!\[[^]]*]\(([^)]+)\)")


@dataclass
class PdfExtractResult:
    markdown: str
    low_quality: bool
    images: list[bytes] = field(default_factory=list)


def _convert(pdf_path: str) -> PdfExtractResult:
    with tempfile.TemporaryDirectory() as image_dir:
        markdown = pymupdf4llm.to_markdown(
            pdf_path,
            write_images=True,
            image_path=image_dir,
            use_ocr=True,
            ocr_language="eng",
            table_output="markdown",
        )
        images = []
        for match in _IMAGE_LINK.finditer(markdown):
            image_path = Path(match.group(1))
            if image_path.is_file() and image_path.resolve().parent == Path(image_dir).resolve():
                images.append(image_path.read_bytes())
        markdown = _IMAGE_LINK.sub("<!-- image -->", markdown)

    if not markdown.strip():
        raise ValueError(f"No text extracted from PDF: {pdf_path}")
    return PdfExtractResult(
        markdown=markdown,
        low_quality=len(markdown.strip()) < _LOW_QUALITY_THRESHOLD,
        images=images,
    )


def extract_pdf(pdf_path: str, return_quality: bool = False) -> str | tuple[str, bool]:
    result = _convert(pdf_path)
    if return_quality:
        return result.markdown, result.low_quality
    return result.markdown


def extract_pdf_full(pdf_path: str) -> PdfExtractResult:
    return _convert(pdf_path)
```

- [ ] **Step 2: Run the PDF corpus tests and verify GREEN**

Run: `python -m pytest tests/test_pdf_ingester.py tests/test_pipeline.py tests/test_integration.py -v`

Expected: all selected deterministic PDF tests PASS. If the scanned or structured fixtures fail, stop this slice and keep Docling; do not weaken the assertions merely to remove the dependency.

- [ ] **Step 3: Commit the PDF slice**

```bash
git add requirements.txt ingesters/pdf.py tests/test_pdf_ingester.py
git commit -m "refactor: use lightweight PDF extraction"
```

## Task 5: Enforce a CPU-Only Runtime

**Files:**
- Create: `tests/test_runtime_dependencies.py`
- Modify: `requirements.txt`
- Modify: `requirements.lock.txt`
- Modify: `requirements-dev.lock.txt`
- Modify: `Dockerfile`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the failing dependency-policy tests**

Create `tests/test_runtime_dependencies.py`:

```python
from pathlib import Path

FORBIDDEN = (
    "openai-whisper",
    "docling",
    "sentence-transformers",
    "torch",
    "torchvision",
    "triton",
    "nvidia-",
)


def test_runtime_lock_excludes_heavy_ml_packages():
    lock = Path("requirements.lock.txt").read_text().lower().splitlines()
    packages = [line for line in lock if line and not line.startswith((" ", "#"))]
    assert not [line for line in packages if line.startswith(FORBIDDEN)]


def test_dockerfile_does_not_install_ffmpeg():
    dockerfile = Path("Dockerfile").read_text().lower()
    assert "ffmpeg" not in dockerfile
```

- [ ] **Step 2: Run the policy tests and verify RED**

Run: `python -m pytest tests/test_runtime_dependencies.py -v`

Expected: both tests FAIL against the old lock and Dockerfile.

- [ ] **Step 3: Remove obsolete direct dependencies**

Delete these lines from `requirements.txt`:

```text
docling==2.123.1
sentence-transformers==6.0.0
transformers==5.8.0
openai-whisper==20250625
```

Keep `fastembed`, `pymupdf4llm`, and `pymupdf-layout` pinned.

- [ ] **Step 4: Regenerate both locks from manifests**

Run:

```bash
uv pip compile requirements.txt --universal --python-version 3.13 --output-file requirements.lock.txt
uv pip compile requirements-dev.txt --universal --python-version 3.13 --output-file requirements-dev.lock.txt
```

Expected: both commands exit 0. Do not edit generated lock entries manually.

- [ ] **Step 5: Slim and align the Dockerfile**

- Remove FFmpeg from builder and runtime apt packages.
- Add `tesseract-ocr` to the runtime apt packages for scanned-PDF OCR.
- Remove the unpinned `pip install playwright` command. Move browser installation after `COPY --from=builder /usr/local/bin /usr/local/bin`, so it uses the Playwright executable and version supplied by the compiled lock:

```dockerfile
RUN python -m playwright install chromium
```

The Python package already comes from `requirements.lock.txt`; do not run a second `pip install playwright` in the runtime stage.

- [ ] **Step 6: Install OCR in CI before tests**

Add this step before Python dependency installation in the `test` and `integration` jobs in `.github/workflows/ci.yml`:

```yaml
      - name: Install PDF OCR dependency
        run: sudo apt-get update && sudo apt-get install --yes --no-install-recommends tesseract-ocr
```

- [ ] **Step 7: Run dependency checks and focused imports**

Run:

```bash
python -m pytest tests/test_runtime_dependencies.py -v
python -m pip check
python -c "import app; import ingesters.pdf; import ingesters.youtube; import core.reranker"
```

Expected: all commands exit 0; policy tests PASS.

- [ ] **Step 8: Commit manifests, locks, image, CI, and policy tests**

```bash
git add requirements.txt requirements.lock.txt requirements-dev.lock.txt Dockerfile .github/workflows/ci.yml tests/test_runtime_dependencies.py
git commit -m "build: remove heavyweight ML runtime"
```

## Task 6: Full Local Verification and Coverage

**Files:**
- Modify only if a verified regression requires a minimal fix.

- [ ] **Step 1: Run static verification**

Run:

```bash
python -m compileall -q app.py pipeline.py config.py core ingesters vault scripts
python -m ruff check app.py pipeline.py config.py core ingesters vault
```

Expected: both commands exit 0.

- [ ] **Step 2: Run the complete test suite**

Run: `python -m pytest tests/ -v`

Expected: 0 failures.

- [ ] **Step 3: Measure coverage required by `test_scope: true`**

Run:

```bash
python -m pytest -q --disable-warnings -m "not integration and not slow" \
  --cov=app --cov=pipeline --cov=core --cov=ingesters --cov=vault \
  --cov-fail-under=60 --cov-report=term-missing
```

Expected: coverage does not drop below the measured pre-change baseline of 66.37% (301 passed, 77 deselected).

- [ ] **Step 4: Build and inspect the Docker image**

Run:

```bash
docker compose build personalwiki
docker compose run --rm personalwiki python -m pip check
docker compose run --rm personalwiki python -c "import importlib.util as i; forbidden=['whisper','docling','torch','torchvision']; assert not any(i.find_spec(name) for name in forbidden)"
```

Expected: image builds; package check exits 0; no forbidden module is importable.

- [ ] **Step 5: Run the container health check**

Run: `docker compose up -d personalwiki`

Poll `docker compose ps` until `personalwiki` is healthy, then verify `curl --fail http://127.0.0.1:8010/` exits 0. Always finish with `docker compose down`.

- [ ] **Step 6: Run local ingestion smoke cases**

Using the application's local UI or existing smoke scripts, verify one website, one representative PDF, one DOCX, one Markdown or text file, and one captioned YouTube video produce useful notes in an isolated temporary vault. Verify an uncaptioned YouTube video produces no note. Do not point smoke tests at the real vault.

- [ ] **Step 7: Record image-size evidence**

Run `docker image inspect personalwiki-personalwiki --format '{{.Size}}'` and include the byte count in the final implementation summary. If no pre-change image exists, report only the final size rather than fabricating a comparison.

- [ ] **Step 8: Final verification commit if needed**

If verification required tracked fixture or script changes, commit only those files with `test: add ingestion slimming acceptance coverage`. If no files changed, do not create an empty commit.
