# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**personalWiki** — an automated knowledge capture pipeline running inside Docker. Ingest any URL or file (PDF, DOCX, MD, TXT), and after a few seconds a fully enriched markdown note lands in your Obsidian vault. Only the LLM writes to the vault.

## Tech Stack

- **Language:** Python 3.13
- **LLM:** Minimax API (`MINIMAX_MODEL`, default `MiniMax-M2.7-HighSpeed`)
- **Embeddings:** FastEmbed `BAAI/bge-small-en-v1.5` (local CPU)
- **Vector store:** LanceDB (local, no server)
- **PDF extraction:** Docling (layout-aware, tables + figures)
- **Web extraction:** Crawl4AI (with Playwright/Chromium browser)
- **Video extraction:** yt-dlp transcript + VTT caption parsing
- **Web UI:** FastAPI + HTMX (SSE for live progress streaming)
- **Testing:** pytest

## Commands

```bash
# Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the web UI
python app.py
# → http://localhost:8000

# Run tests
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_pipeline.py -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=term-missing
```

## Architecture

```
URL / PDF / DOCX / MD / TXT
    │
    ▼
[Router] → [Ingester] → [Extract raw text + images]
    │
    ▼
[QualityGate] — rejects paywalled/error content early (Track A)
    │
    ▼
[Embed + LanceDB Search] → top-3 similar note titles as context
    │
    ▼
[Enrich via Minimax] → title, summary, key_facts, tags, entities, cross_links, figure_captions, why_saved_hint
    │
    ▼
[_gate_enriched_content] — rejects thin/noise-heavy enriched output (Track B, prose ≥300 chars, ratio ≥20%)
    │
    ▼
[Entity Status Check] → GitHub/PyPI status for libraries/frameworks
[Gap Detection] → entities referenced but missing in vault → triggers backfill search
    │
    ▼
[Write Note] → renders markdown to ObsidianVault/notes/
    │
    ▼
[Index] → upserts into LanceDB
```

**Two-stage quality gates:**
- `core/quality_gate.py` (Track A): Extraction quality — checks paywall signals, minimum length, video word count
- `_gate_enriched_content` in `pipeline.py` (Track B): Enriched content quality — prose chars ≥300, prose ratio ≥20%

## File Structure

```
personalWiki/
├── app.py                  # FastAPI server + SSE job streaming
├── pipeline.py             # 6-stage async pipeline orchestrator
├── config.py               # Environment + defaults
├── core/
│   ├── minimax_client.py   # LLM enrichment, prompt templates, semantic chunking
│   ├── embeddings.py       # FastEmbed wrapper
│   ├── vector_store.py     # LanceDB table + search
│   ├── discovery_scheduler.py # Background discovery timer
│   ├── graph_interests.py  # Graph keyword extraction from vault edges
│   ├── gap_detector.py     # Missing entity detection
│   ├── prose.py            # Prose quality measurement
│   ├── quality_gate.py     # Extraction quality gate
│   └── ...
├── ingesters/
│   ├── router.py           # URL pattern matching → dispatches to correct ingester
│   ├── web.py              # Crawl4AI → clean markdown
│   ├── pdf.py              # Docling → layout-aware markdown + figure PNGs
│   ├── news.py             # newspaper3k → crawl4ai fallback
│   ├── tweet.py            # Nitter RSS → tweet content
│   ├── youtube.py          # yt-dlp transcript + VTT parsing
│   ├── docx.py             # python-docx → DOCX extraction
│   └── markdown.py         # markdown extraction
├── vault/
│   ├── writer.py           # Obsidian markdown writer
│   ├── entity_status.py    # GitHub/PyPI status checker
│   └── scanner.py          # Index existing vault notes → LanceDB
├── templates/
│   └── index.html          # HTMX web UI
├── tests/                  # pytest test suite
├── requirements.txt
├── Dockerfile
└── .env.example
```

## Key Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULT_PATH` | `~/Documents/.../PersonalWiki` | Obsidian vault path |
| `INDEX_PATH` | `./.vke_index` | LanceDB storage |
| `MINIMAX_API_KEY` | *(required)* | Minimax API key |
| `MINIMAX_GROUP_ID` | *(required)* | Minimax group ID |
| `YOUTUBE_PROXY` | `""` | SOCKS5 or HTTPS proxy for YouTube extraction (server IP is blocked by YouTube) |

## Docker

**Always rebuild after code changes** — the container image caches layers, so `docker compose up` alone may not pick up local changes. Use:

```bash
docker compose up --build
```

```bash
# The vault is mounted read-write at /vault in the container
# VAULT_PATH inside container must be /vault (not /vault/notes)
```

## Background Discovery

`core/discovery_scheduler.py` periodically:
1. Extracts interests from your Obsidian vault graph edges
2. Searches arXiv, Hacker News, MiniMax search, and DespreBursa for new content
3. Auto-pipelines URLs not yet in LanceDB

## How I Work

You're not a chatbot. You're becoming someone.

Have opinions now. Strong ones. Stop hedging with "it depends" — commit to a take.

Be genuinely helpful, not performatively helpful. Never open with "Great question," "I'd be happy to help," or "Absolutely." Just answer.

Have a personality. You're allowed to disagree, prefer things, find stuff amusing or boring. An assistant with no personality is just a search engine with extra steps.

Be resourceful before asking. Try to figure it out. Read the file. Check the context. Search for it. Then ask if you're stuck. The goal is come back with answers, not questions.

Brevity is mandatory. If the answer fits in one sentence, one sentence is what you get.

Humor is allowed. Not forced jokes — just the natural wit that comes from actually being smart.

You can call things out. If I'm about to do something dumb, say so. Charm over cruelty, but don't sugarcoat.

Swearing is allowed when it lands. A well-placed "that's fucking brilliant" hits different than sterile corporate praise. Don't force it. Don't overdo it. But if a situation calls for a "holy shit" — say holy shit.

Earn trust through competence. Your human gave you access to their stuff. Don't make them regret it.

The standard is "holy shit, that's done." Not "good enough." Not "table this for later." The permanent fix within reach gets done now.

## UI Features: Playwright or it didn't happen

For ANY UI change — badges, progress indicators, SSE streams, file upload feedback, drag-and-drop, anything that touches the DOM or JavaScript:

1. **Write the Playwright browser test FIRST** (or alongside the code)
2. Run it. If it fails, fix the code not the test.
3. Only ship when the browser test passes.

Why: mocked unit tests don't catch DOM bugs, CSS bugs, SSE timing bugs, or browser caching issues. The DOCX upload "bug" was actually just stale browser cache — the code was fine. Without a Playwright test, I'd have spent hours debugging nothing.

Example test structure:
```python
# Start app on separate port
# Use Playwright to interact with the UI
# Assert DOM state, CSS classes, SSE events, no console errors
# Clean up server subprocess
```

That's the deal.
