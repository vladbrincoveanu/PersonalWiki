# PDF Image Extraction — Design Spec

**Date:** 2026-04-11  
**Status:** Approved

## Goal

Replace every `<!-- image -->` placeholder in PDF-extracted markdown with a real Obsidian image link (`![[attachments/<slug>/figure-N.png]]`), backed by the actual PNG saved to disk at `VAULT_PATH/attachments/<slug>/figure-N.png`.

## Background

Docling converts PDFs to markdown but silently drops figures as `<!-- image -->` HTML comments. For arxiv papers and technical documents, these are architecture diagrams, result graphs, and figures that carry significant meaning. This feature extracts them as real images and embeds them at their original positions in the note.

## Storage Layout

Images are stored at:
```
VAULT_PATH/
  attachments/
    <note-slug>/
      figure-1.png
      figure-2.png
      ...
  notes/
    <note-slug>.md
```

Obsidian resolves `![[attachments/<slug>/figure-N.png]]` wikilinks from the vault root, so this layout works out of the box.

## Components

### `ingesters/pdf.py`

- Add a `PdfExtractResult` dataclass with fields: `markdown: str`, `low_quality: bool`, `images: list[bytes]`
- Add `extract_pdf_full(pdf_path: str) -> PdfExtractResult`
  - Configures `PdfPipelineOptions(generate_picture_images=True)`
  - After conversion, collects PNG bytes from `result.document.pictures` in document order
  - Returns `PdfExtractResult` — images list is parallel to `<!-- image -->` occurrences in the markdown
- Keep existing `extract_pdf()` unchanged for backward compatibility

### `pipeline.py`

- For PDF paths (both direct and URL-downloaded), call `extract_pdf_full()` instead of `extract_pdf()`
- Extract `raw_text = result.markdown` and `images = result.images`
- Pass `images` through to `write_note()`

### `vault/writer.py`

- `write_note()` gains `images: list[bytes] = ()` parameter
- When `images` is non-empty:
  - Derive `slug` from the note title (already computed for the filename)
  - Create `VAULT_PATH/attachments/<slug>/` directory
  - Save each image as `figure-1.png`, `figure-2.png`, … (1-indexed)
  - Sequentially replace each `<!-- image -->` occurrence in `raw_text` with `![[attachments/<slug>/figure-N.png]]`
- When `images` is empty: no-op, behavior unchanged

## Data Flow

```
PDF path/URL
    → docling (generate_picture_images=True)
    → PdfExtractResult(markdown, low_quality, images: list[bytes])
    → pipeline.py extracts (raw_text, images)
    → enrich(raw_text, ...) → note dict
    → write_note(note, source, images=images)
    → vault/attachments/<slug>/figure-N.png saved
    → <!-- image --> replaced with ![[attachments/<slug>/figure-N.png]]
    → note written to vault/notes/<slug>.md
```

## Edge Cases

- **PDF with no images:** `images=[]`, `write_note` no-ops the image logic, behavior identical to today
- **More `<!-- image -->` tags than images:** Leave extras as `<!-- image -->` (should not happen with well-formed PDFs)
- **Web URLs:** `extract_url()` is unchanged; `write_note()` called without `images` parameter
- **Slug collision:** Images directory uses the same slug as the note file (with counter suffix if needed); pass final slug to image-saving logic

## Out of Scope

- Downloading or saving images from web pages (they remain as `![alt](https://...)` links)
- AI-powered image descriptions (Option C)
- Page-level PDF rendering (only per-figure extraction)
