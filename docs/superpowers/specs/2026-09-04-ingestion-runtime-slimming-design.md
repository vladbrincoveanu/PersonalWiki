---
title: Ingestion Runtime Slimming
date: 2026-09-04
status: approved
ui_scope: false
graph_scope: false
test_scope: true
---

# Ingestion Runtime Slimming

## Goal

Reduce the local and Docker runtime footprint without removing the core capability to ingest websites, PDFs, DOCX, Markdown, text, tweets, and captioned YouTube videos. Work proceeds in small vertical slices, with local verification after every slice. Hosting and Terraform are deferred.

## Scope

### Included

- Remove local Whisper transcription and FFmpeg.
- Keep YouTube transcript API and `yt-dlp` subtitle extraction.
- Reject videos that have no usable transcript instead of saving title/description-only notes.
- Replace the Torch-based search reranker with an ONNX-backed FastEmbed reranker.
- Replace Docling PDF extraction with a PyMuPDF-based implementation while preserving the existing PDF extraction interface.
- Regenerate production and development dependency locks.
- Prove the resulting runtime contains no Whisper, Docling, Torch, torchvision, Triton, CUDA, or NVIDIA runtime packages.
- Keep Crawl4AI and Chromium unchanged during this phase to protect website ingestion quality.

### Excluded

- Hosting, Terraform, domains, authentication, and remote deployment.
- Redesigning autonomous discovery, the UI, vault structure, enrichment, or indexing.
- Supporting audio transcription for videos without captions.
- Replacing Crawl4AI or Chromium.
- Adding distributed workers, queues, or multiple application processes.

## Compatibility Contract

The pipeline continues to accept the same URL and file inputs. Website, PDF, DOCX, Markdown, text, tweet, and captioned YouTube inputs continue through extraction, enrichment, quality gating, vault writing, and indexing. The only intentional behavior change is that an uncaptioned YouTube video produces the existing `[NO_TRANSCRIPT]` extraction signal immediately; the quality gate rejects it before a note is written.

This narrows the fallback behavior introduced by the [YouTube Transcript API design](./2026-04-13-youtube-transcript-api-design.md): local Whisper and metadata-only fallback are removed, while transcript API and subtitle tiers remain. PDF output retains the `PdfExtractResult` contract established by the [PDF image extraction design](./2026-04-11-pdf-image-extraction-design.md). Hybrid retrieval remains compatible with the [hybrid search design](./2026-04-13-hybrid-search-design.md).

## Modules

### Module: YouTube Transcript Ingester

- **Responsibility:** Return transcript text from YouTube-provided captions or the existing no-transcript signal.
- **Interface:** `extract_youtube(url) -> Document`; successful documents contain transcript text and use content type `video`.
- **Dependencies:** `youtube-transcript-api`, `yt-dlp`, proxy configuration, and the existing quality gate.
- **Size target:** Keep `ingesters/youtube.py` below 260 lines after deleting audio-transcription and metadata-only fallback code.

The adapter order remains transcript API first and `yt-dlp` subtitle tiers second. Failure of every caption adapter returns `[NO_TRANSCRIPT]`. It does not download audio, invoke FFmpeg, load a model, or save title/description-only content.

### Module: Search Reranker

- **Responsibility:** Rerank merged hybrid-search candidates without PyTorch.
- **Interface:** Preserve `CrossEncoderReranker.rerank(query, results, top_k) -> list[dict]`, including fallback to original ordering when model loading or scoring fails.
- **Dependencies:** FastEmbed's ONNX cross-encoder adapter and existing result dictionaries.
- **Size target:** Keep `core/reranker.py` below 60 lines.

The module changes its implementation, not its interface. Callers in the vector store remain unchanged. Model initialization stays lazy and cached. Tests inject a model adapter and assert observable ranking rather than implementation details.

### Module: PDF Extractor

- **Responsibility:** Extract useful Markdown, quality status, and image bytes from local or downloaded PDFs without Docling.
- **Interface:** Preserve `extract_pdf`, `extract_pdf_full`, and `PdfExtractResult(markdown, low_quality, images)`.
- **Dependencies:** PyMuPDF-based packages and the filesystem path supplied by the router.
- **Size target:** Keep `ingesters/pdf.py` below 100 lines.

Text extraction produces Markdown suitable for the existing enrichment pipeline. Image extraction remains best-effort: images are returned in document order when practical, and a PDF with no extractable images still succeeds. Empty extraction remains an error. Extraction shorter than the existing threshold remains low quality. Existing callers and vault-writing interfaces do not change.

### Module: Runtime Image

- **Responsibility:** Build and run the application with only required system and Python dependencies.
- **Interface:** The existing Docker command, port, health check, and environment variables remain unchanged.
- **Dependencies:** The compiled production lock, Chromium system libraries, and Playwright browser installation required by Crawl4AI.
- **Size target:** Keep the Dockerfile as one builder stage and one runtime stage, below 80 lines.

FFmpeg leaves both Docker stages. Playwright remains pinned consistently with the Python dependency lock. The image must not contain packages from the prohibited heavyweight set listed in the verification section.

## Delivery Slices

1. **YouTube:** write failing behavior and dependency tests, remove Whisper/audio/metadata fallback, remove FFmpeg and `openai-whisper`, regenerate locks, then run focused and full tests.
2. **Reranker:** write failing interface tests for the FastEmbed adapter, replace sentence-transformers, remove direct sentence-transformers and transformers requirements when no longer directly used, regenerate locks, then run focused and full tests.
3. **PDF:** write extractor contract tests against representative fixtures, replace Docling while preserving `PdfExtractResult`, remove Docling requirements, regenerate locks, then run focused and full tests.
4. **Runtime proof:** build the Docker image, inspect installed packages, run the container, and execute local smoke ingestion across the supported input matrix.

A slice may remove a dependency only after its replacement behavior passes. No slice combines unrelated scheduler, persistence, security, or deployment changes.

## Error Handling

- Caption lookup failures are recoverable between transcript adapters; exhaustion returns `[NO_TRANSCRIPT]` for the existing quality gate.
- PDF extraction raises a clear `ValueError` for invalid or empty content and preserves the low-quality signal for short content.
- Reranker initialization or inference failure logs a warning and returns the existing candidate order.
- Dependency-lock generation or Docker build failure stops the slice; manually deleting transitive lock entries is forbidden.

## Verification

### Regression Tests

- Transcript API success returns a video document.
- `yt-dlp` captions remain the second adapter.
- Videos with no transcript return `[NO_TRANSCRIPT]` without audio download or metadata fallback.
- The quality gate prevents no-transcript content from being written.
- Reranking changes candidate order and preserves fallback behavior.
- Text-only, image-bearing, short, empty, and invalid PDFs satisfy the preserved extractor contract.
- Website, DOCX, Markdown, text, and tweet regression suites remain green.

### Dependency Assertions

The compiled Linux runtime dependency set must not include:

- `openai-whisper`
- `docling` or any `docling-*` package
- `sentence-transformers`
- `torch` or `torchvision`
- `triton`
- packages prefixed `nvidia-`

The Dockerfile must not install FFmpeg. Chromium and Playwright remain expected in this phase.

### Local Acceptance Matrix

- Full pytest suite passes.
- Ruff passes on production source.
- Docker image builds from the committed lock.
- Container health check passes.
- One representative website saves useful content.
- One representative PDF saves useful content.
- DOCX, Markdown, and text uploads save useful content.
- A captioned YouTube video saves a transcript-backed note.
- An uncaptioned YouTube video saves no note.
- Hybrid search returns ranked results after the reranker replacement.

Measure and record the final image size and compare it with the pre-change image if the current image can be built locally. The size comparison is evidence, not a release gate; removal of the prohibited dependency set is the deterministic gate.

## Rollback

Each delivery slice is independently revertible. If the replacement PDF extractor materially degrades representative content, retain the completed YouTube and reranker slices and stop before removing Docling. Do not restore Whisper or CUDA merely to keep the PDF slice moving.
