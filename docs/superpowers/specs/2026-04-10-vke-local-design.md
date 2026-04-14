# VKE-Local Design Spec
**Date:** 2026-04-10  
**Status:** Approved

---

## Overview

VKE-Local (Verified Knowledge Engine) transforms an Obsidian vault into a graph-aware, queryable knowledge base. The primary workflow is **ingest-first**: the user feeds URLs and PDFs via a local web app and receives enriched Markdown notes saved directly into Obsidian.

**Tech stack:**
- Reasoning: Minimax API (`abab6.5s-chat`)
- Embeddings: FastEmbed, `BAAI/bge-small-en-v1.5` (local CPU, zero cost)
- Vector store: LanceDB (local file on disk, no server)
- Web ingestor: Crawl4AI
- PDF ingestor: Docling (layout-aware, handles tables/headers)
- Web UI: FastAPI + HTMX

**Key directories:**
- Project code: `/Users/vladbrincoveanu/Desktop/Startup/personalWiki/`
- Vault data: `/Users/vladbrincoveanu/Documents/ObsidianVault/` (cleaned, starting fresh)
- LanceDB index: `personalWiki/.vke_index/` (gitignored)

---

## Architecture

```
personalWiki/
├── config.py               ← vault path, API keys, model config
├── app.py                  ← FastAPI server (web UI + SSE job stream)
├── core/
│   ├── embeddings.py       ← FastEmbed wrapper
│   ├── vector_store.py     ← LanceDB table init, upsert, search
│   └── minimax_client.py   ← Minimax chat completions wrapper
├── ingesters/
│   ├── web.py              ← Crawl4AI → clean Markdown from URL
│   └── pdf.py              ← Docling → layout-aware Markdown from PDF
├── pipeline.py             ← orchestrates ingest → enrich → write → index
├── vault/
│   ├── writer.py           ← saves enriched note to ObsidianVault/notes/
│   └── scanner.py          ← indexes existing vault notes into LanceDB
├── templates/
│   └── index.html          ← HTMX web UI
└── .vke_index/             ← LanceDB storage (gitignored)

ObsidianVault/
└── notes/                  ← all ingested notes, flat, tagged via frontmatter
```

---

## Data Flow

1. User pastes URL or drops PDF in web UI at `http://localhost:8000`
2. FastAPI spawns background job, streams progress via Server-Sent Events
3. Ingester extracts raw Markdown (Crawl4AI for URLs, Docling for PDFs)
4. LanceDB queried for top-3 semantically similar existing notes
5. Minimax called with: raw text + similar note titles + output template
6. Enriched note written to `ObsidianVault/notes/<slug>.md`
7. New note upserted into LanceDB index

---

## Note Format

Every note saved to `ObsidianVault/notes/<slug>.md` where slug = title lowercased, spaces→hyphens, special chars stripped (e.g. "PagedAttention Paper" → `pagedattention-paper.md`):

```markdown
---
title: "Note Title"
source: https://example.com/or/path/to/file.pdf
type: paper          # paper | article | video | personal
tags: [tag1, tag2]
ingested: 2026-04-10
---

## Summary
2-3 sentence synthesis by Minimax.

## Key Facts
- Bullet points extracted from the source.

## My Knowledge Says
Cross-links to similar notes already in vault: [[existing-note-1]], [[existing-note-2]]

## Raw Extract
<details>
<summary>Original extracted text</summary>

...raw content here...

</details>
```

The "My Knowledge Says" section is populated by querying LanceDB for similar notes before calling Minimax, then injecting their titles as context so Minimax can produce relevant cross-links.

---

## LanceDB Schema

Each record in the LanceDB table:

| Field | Type | Description |
|-------|------|-------------|
| `path` | string (ID) | Relative path from vault root — used for upserts |
| `text` | string | Full note content |
| `vector` | float[] | FastEmbed embedding (384 dims) |
| `links` | string[] | `[[wikilinks]]` found in the note |
| `metadata` | JSON | title, source, type, tags, ingested date |

---

## Web UI

Single-page app at `http://localhost:8000`. Progress streams via HTMX SSE (no polling, no reload).

```
┌─────────────────────────────────────┐
│  VKE Local                          │
│                                     │
│  [ Paste URL                    ]   │
│  [ Choose PDF file... ] (upload)    │
│                                     │
│  [ Ingest ]                         │
│                                     │
│  ─── Progress ───────────────────   │
│  ✓ Extracting content...            │
│  ✓ Finding similar notes (3 found)  │
│  ✓ Enriching with Minimax...        │
│  ✓ Saved → notes/paged-attention.md │
└─────────────────────────────────────┘
```

---

## Vault Scanner

`vault/scanner.py` — run as a one-time CLI command to index existing notes:

```bash
python vault/scanner.py
```

Also triggered automatically on app startup if the LanceDB index is empty. Walks `ObsidianVault/notes/`, parses YAML frontmatter and `[[wikilinks]]`, upserts into LanceDB. Uses file modification timestamps for incremental updates on subsequent runs.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| URL unreachable or paywalled | Show error in UI, no note written |
| PDF with poor text quality | Save raw extract with `confidence: low` in frontmatter |
| Minimax down or rate-limited | Retry once, then save raw extract without enrichment |
| Duplicate URL | Detect via LanceDB path lookup, prompt "update existing note?" |

---

## Out of Scope

- Multi-user access
- Authentication on the local server
- Scheduled or background ingestion
- Chat/RAG query interface (future phase)

---

## Dependencies

```
fastapi
uvicorn
crawl4ai
docling
fastembed
lancedb
requests
python-frontmatter
python-dotenv
```

---

## Startup

```bash
python app.py
# → Server starts at http://localhost:8000
# → Scanner runs in background if index is empty
```
