# personalWiki as LLM Memory Bank — Design Spec

**Date:** 2026-04-28
**Status:** Approved
**Goal:** personalWiki stores compressed personal + web knowledge, accessible to humans (Obsidian) and LLMs (MCP read-only)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    personalWiki                           │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │ Ingestion   │  │ LM Studio   │  │ MCP Server    │ │
│  │ Pipeline    │→ │ qwen3-embed │→ │ (FastMCP)     │ │
│  │ (YouTube,   │  │ localhost   │  │ read-only     │ │
│  │  PDF, docx) │  │ :1234       │  │               │ │
│  └─────────────┘  └──────────────┘  └───────────────┘ │
│  ┌─────────────┐  ┌──────────────┐                     │
│  │ Discovery   │→ │ Gap         │→ Obsidian Vault    │
│  │ Scheduler   │  │ Detector    │                     │
│  └─────────────┘  └──────────────┘                     │
└─────────────────────────────────────────────────────────┘
                         ↓
              LLM (MiniMax, DeepSeek)
              via MCP (read queries only)
```

---

## Implementation Phases

### Phase 1: Stabilize Current System

**1.1 Fix YouTube ingestion**
- Trace exact failure point: transcription → quality gate → write → index
- Fix whisper fallback logic if transcription fails
- Ensure quality gate doesn't reject valid transcripts

**1.2 Fix "content without keywords" bug**
- Identify what triggers the bug (discovery or ingestion)
- Adjust quality gate thresholds or discovery loop logic

**1.3 Make discovery scheduler idempotent**
- Add retry logic with exponential backoff
- Ensure same URL isn't re-processed multiple times

### Phase 2: Embedding Upgrade

**2.1 Integrate qwen3-embedding-4b via LM Studio**
- Replace bge-small (FastEmbed) with qwen3-embedding-4b
- API: `POST http://localhost:1234/api/v1/chat` with model `qwen3-embedding-4b-dwq`
- Update `core/embeddings.py` to call LM Studio instead of FastEmbed

**2.2 Fresh LanceDB index**
- qwen3-embedding-4b produces ~1024d embeddings (vs 384d bge-small)
- Wipe `.vke_index/` and re-index entire vault
- Keep bge-small path as fallback if LM Studio unavailable

**2.3 Update vector_store.py schema**
- Change embedding dimension from 384 to match qwen3 output
- Update all LanceDB table schemas accordingly

### Phase 3: MCP LLM Memory (FastMCP, embedded)

**3.1 Add FastMCP server**
- Integrate via `fastmcp` Python package
- Attach to existing FastAPI/FastAPI server on `/mcp` endpoint

**3.2 Expose MCP tools (read-only)**

| Tool | Responsibility | Returns |
|------|---------------|---------|
| `memory.search(query)` | Vector + BM25 + graph hybrid search | Top K chunks with scores |
| `memory.get_about_vlad()` | Query personal_entities table | Structured summary of projects, investments, preferences |
| `memory.get_project_context(name)` | Search by project name | Everything about a specific project |
| `memory.get_recent(max=5)` | Time-based query | Recently added/updated knowledge |

**3.3 Flexible entity extraction on ingest**
- During pipeline enrichment, extract entities (projects, people, companies, investments)
- Store in separate LanceDB table: `personal_entities`
- Schema: `{path, entity_type, entity_name, summary, metadata}`
- No fixed schema — let extraction discover structure

### Phase 4: gbrain Workflows (ongoing)

**4.1 Adopt skills for development**
- `brainstorming` — before adding new ingesters/features
- `systematic-debugging` — when ingestion fails
- `verification-before-completion` — before claiming bug fixed

---

## Module Design Blocks

### Module: `core/embeddings.py`
- **Responsibility:** Generate embeddings for text chunks
- **Interface:** `embed(texts: list[str]) → list[list[float]]`
- **Dependencies:** LM Studio API (localhost:1234), fallback to FastEmbed
- **Size target:** ~100 lines

### Module: `core/vector_store.py`
- **Responsibility:** LanceDB CRUD for notes and entities
- **Interface:** `upsert_chunk()`, `search()`, `get_recent()`, `upsert_entity()`
- **Dependencies:** LanceDB, embeddings.py
- **Size target:** ~200 lines

### Module: `mcp_server.py` (NEW)
- **Responsibility:** FastMCP server exposing memory tools to LLMs
- **Interface:** 4 tools exposed via MCP protocol
- **Dependencies:** FastMCP, vector_store.py, embeddings.py
- **Size target:** ~150 lines

### Module: `core/entity_extractor.py` (NEW)
- **Responsibility:** Extract structured entities from content during ingest
- **Interface:** `extract_entities(text: str) → list[dict]`
- **Dependencies:** MiniMax LLM (via minimax_client.py)
- **Size target:** ~150 lines

### Module: `pipeline.py`
- **Responsibility:** Orchestrate ingestion (extract → enrich → quality gate → write → index)
- **Interface:** `run_pipeline(url)`, `run_discovery()`
- **Dependencies:** ingesters/, entity_extractor.py, vector_store.py
- **Bug fixes:** YouTube fallback, quality gate thresholds, idempotent discovery

---

## Out of Scope (for now)

- MCP write-back (LLMs cannot write to memory yet)
- Code indexing (KnowledgeForge concern)
- Mobile ingestion
- Non-LM-Studio embedding models
- Job queue / minions

---

## Fresh Start

- Wipe `.vke_index/` — re-index everything with qwen3 embeddings
- personalWiki keeps existing vault (Obsidian markdown files)
- MCP tools query existing + new content

---

## Success Criteria

1. YouTube video URL processes reliably → transcript → indexed
2. "Content without keywords" no longer crashes or loops
3. Discovery scheduler runs without duplicates or failures
4. `memory.search()` returns relevant results via MCP (tested with MiniMax)
5. Entity extraction finds projects/people/investments in ingested content
6. gbrain brainstorming/debugging/verification workflows adopted