# personalWiki — VKE-Local

**Ingest any URL or PDF, get a structured Obsidian note.**

personalWiki is an automated knowledge capture pipeline. Paste a link or drop a PDF — after a few seconds a fully enriched markdown note lands in your Obsidian vault with title, tags, summary, key facts, cross-links to existing notes, extracted entities, figure captions, and a personal "why I saved this" hook.

Only the LLM writes to the vault. The user's only job is to feed content in.

---

## Supported Sources

| Source | Ingester | Details |
|--------|----------|---------|
| arXiv papers | PDF | Downloads PDF, extracts via Docling with layout awareness |
| General URLs | Web | Crawl4AI extracts clean markdown |
| News articles | News | newspaper3k → crawl4ai fallback → raw extract |
| Tweets / X posts | Tweet | Nitter RSS with instance rotation |
| YouTube videos | Video | yt-dlp transcript + VTT caption parsing |
| Local PDFs | PDF | Docling with figure extraction |

The **URL router** (`ingesters/router.py`) dispatches automatically based on domain and URL pattern matching.

---

## Architecture

```
URL / PDF → [Router] → [Ingester] → [Extract] → [Vector Search] → [LLM Enrich] → [Write Note] → [Index]
                                                 ↓
                              Similar notes from LanceDB ←───
```

**Background Discovery (`core/discovery_scheduler.py`)**:
- Periodically extracts "interests" automatically from your Obsidian graph.
- Searches for new content across arXiv, Hacker News, MiniMax search, and DespreBursa.
- Automatically pipelines newly discovered URLs if they aren't in LanceDB yet.

**Pipeline (`pipeline.py`):**
1. **Extract** — Raw markdown from URL (via router) or PDF (via Docling)
2. **Find similar** — Embed query via FastEmbed, search LanceDB for top-3 similar notes
3. **Enrich** — Minimax LLM synthesizes title, summary, key facts, tags, entities, cross-links, figure captions, "why I saved this"
4. **Resolve Entities** — Checks GitHub/PyPI for library statuses and detects missing "gap entities" in your vault (triggering backfill searches)
5. **Write** — Saves structured `.md` note to `ObsidianVault/notes/`
6. **Index** — Upserts note into LanceDB for future retrieval

**Core modules:**
- `core/minimax_client.py` — Minimax API wrapper, prompt templates per content type
- `core/embeddings.py` — FastEmbed wrapper (`BAAI/bge-small-en-v1.5`, 384 dims, local CPU)
- `core/vector_store.py` — LanceDB table init, upsert, vector similarity search
- `core/discovery_scheduler.py` — Background timer triggering discovery loops
- `core/graph_interests.py` — Extracts keywords from Vault graph node edges
- `core/gap_detector.py` — Detects entities referenced but missing in vault
- `ingesters/router.py` — URL pattern matching, routes to correct ingester
- `vault/writer.py` — Obsidian markdown writer, handles image placeholders, entity stubs
- `vault/entity_status.py` — GitHub/PyPI status checker for tools/libraries
- `vault/scanner.py` — CLI to index existing vault notes into LanceDB

**Ingesters (`ingesters/`):**
- `web.py` — Crawl4AI → clean markdown from any URL
- `pdf.py` — Docling → layout-aware markdown + figure PNGs from PDFs
- `news.py` — newspaper3k → article extraction with crawl4ai fallback
- `tweet.py` — Nitter RSS → tweet content with instance rotation
- `youtube.py` — yt-dlp transcript + VTT caption parsing

---

## Note Format

Every note has YAML frontmatter and structured sections:

```markdown
---
title: "PagedAttention: Secure Virtual Memory for LLM Serving"
source: https://arxiv.org/abs/2309.11157
type: paper
tags: [LLM-serving, KV-cache, GPU, vLLM]
ingested: 2026-04-12
---

## Summary
PagedAttention manages KV cache in non-contiguous virtual memory pages...

## Key Facts
- Eliminates memory fragmentation in LLM inference
- Achieves 2x higher throughput vs vLLM v1
- Supports speculative decoding with no extra memory cost

## Entities
[[PagedAttention]] · [[vLLM]] · [[KV-cache]]

## Why I Saved This
> GPU memory management for LLM serving is an unsolved problem...

## My Knowledge Says
[[kv-cache]] · [[llm-inference]]

## Raw Extract
<details>
<summary>Original extracted text</summary>

...

</details>
```

---

## Setup

```bash
# 1. Clone
git clone https://github.com/yourusername/personalWiki.git
cd personalWiki

# 2. Create venv and install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env: set MINIMAX_API_KEY, MINIMAX_GROUP_ID, VAULT_PATH

# 4. Index existing vault notes (optional — runs automatically if index is empty)
python vault/scanner.py

# 5. Start the web UI
python app.py
# → http://localhost:8000
```

**Or run the pipeline directly in Python:**
```python
import asyncio
from pipeline import run_pipeline

async for msg in run_pipeline(url="https://arxiv.org/abs/2309.11157"):
    print(msg)
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_PATH` | `~/Documents/ObsidianVault` | Path to Obsidian vault |
| `INDEX_PATH` | `./.vke_index` | LanceDB storage directory |
| `MINIMAX_API_KEY` | *(required)* | Minimax API key |
| `MINIMAX_GROUP_ID` | *(required)* | Minimax group ID |
| `MINIMAX_MODEL` | `abab6.5s-chat` | Minimax model name |

---

## Data Flow Detail

```
User input (URL or PDF)
       │
       ▼
   [Router] — pattern-matches URL → routes to ingester
       │
       ▼
  [Ingester] — extracts raw_text + images + content_type
       │
       ▼
  [Embed + Search] — FastEmbed → LanceDB vector search
       │              ← similar note titles injected as context
       ▼
  [Enrich] — Minimax LLM → structured JSON note dict
       │
       ▼
  [Entity Checks] — Fetch lib status (GitHub/PyPI) & run Gap Detection searches
       │
       ▼
  [Write Note] — renders markdown to ObsidianVault/notes/
       │           saves figure images to vault/attachments/
       │           creates entity stub notes for new entities
       ▼
  [Index] — upserts into LanceDB for future retrieval
```

---

## Tech Stack

- **LLM:** Minimax `abab6.5s-chat`
- **Embeddings:** FastEmbed `BAAI/bge-small-en-v1.5` (local CPU)
- **Vector store:** LanceDB (local, no server)
- **PDF extraction:** Docling (layout-aware, tables + figures)
- **Web extraction:** Crawl4AI
- **News extraction:** newspaper3k → crawl4ai fallback
- **Tweet extraction:** Nitter RSS with instance rotation
- **Video extraction:** yt-dlp transcript + VTT caption parsing
- **Web UI:** FastAPI + HTMX (SSE for live progress streaming)
- **Obsidian format:** python-frontmatter for YAML frontmatter
- **Autonomous Discovery:** Background scheduler probing Hacker News, arXiv, and Web via graph-derived interests

---

## Project Structure

```
personalWiki/
├── app.py                  # FastAPI server + SSE job streaming
├── pipeline.py             # 5-stage async pipeline orchestrator
├── config.py               # Environment + defaults
├── core/
│   ├── minimax_client.py   # LLM enrichment + prompt templates
│   ├── embeddings.py       # FastEmbed wrapper
│   ├── vector_store.py     # LanceDB table + search
│   ├── discovery_scheduler.py # Background discovery timer
│   ├── graph_interests.py  # Graph keyword extraction
│   └── gap_detector.py     # Missing entity detection
├── ingesters/
│   ├── router.py           # URL → ingester dispatcher
│   ├── web.py              # Crawl4AI web extraction
│   ├── pdf.py              # Docling PDF extraction
│   ├── news.py             # newspaper3k + crawl4ai fallback
│   ├── tweet.py            # Nitter tweet extraction
│   └── youtube.py          # yt-dlp transcript + VTT parsing
├── vault/
│   ├── writer.py           # Obsidian markdown writer
│   ├── entity_status.py    # Fetches GitHub/PyPI statuses
│   └── scanner.py          # Index existing vault notes → LanceDB
├── templates/
│   └── index.html          # HTMX web UI
├── requirements.txt
└── .env.example
```
