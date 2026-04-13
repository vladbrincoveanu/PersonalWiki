# VKE-Local: Autonomous Knowledge Discovery — Phase 1

## Status

Proposed · 2026-04-13

## Overview

VKE-Local grows its own knowledge base without any manual input. It reads the existing vault graph to discover what topics the user cares about (hub and leaf nodes), then continuously searches for new content on those topics and ingests it automatically. Gap detection fills entity holes after each ingestion.

**Principle:** No seed files. No review inbox. No manual triggers. The graph is the interest model.

---

## Architecture

```
Vault (Obsidian .md files)
  │
  ▼
[Graph Analyzer] ──→ Top-N interests (hub + leaf nodes)
  │                        │
  │                        ▼
  │              [Discovery Scheduler] (timer-based)
  │                        │
  │                        ├── MiniMax Web Search (per interest)
  │                        ├── arXiv feed check
  │                        ├── YouTube channel search
  │                        └── HN / Nitter RSS
  │                        │
  │                        ▼
  │              [Deduplication] against existing vault URLs
  │                        │
  │                        ▼
  │              [Pipeline] ──→ Ingested .md note
  │                        │
  │                        ▼
  │              [Gap Detection] ──→ Entity follow-up searches
  │                        │           (loop back to scheduler)
  │                        │
  └────────────────────────┘
```

---

## Component 1: Graph Interest Extractor

**File:** `core/graph_interests.py`

### Behavior

1. Scan all `.md` files in `VAULT_PATH`
2. Parse wikilinks (`[[note]]`) from each file's content
3. Build a directed graph: nodes = note titles, edges = wikilinks
4. Score each node:
   - **Hub score** = number of inbound + outbound links
   - **Leaf score** = outbound links only (specialized, self-contained topics)
5. Take top-K by hub score + top-K by leaf score → union as interest keywords
6. Also extract tags from frontmatter (`tags:` YAML field) as keyword seeds
7. Return deduplicated list of keyword strings

### Output

```python
# Example output
["PagedAttention", "KV-cache", "RLHF", "vLLM", "startup fundraising",
 "knowledge graph", "Vector数据库", ...]
```

### Configuration

- `INTEREST_HUB_TOP_K = 15` — how many hub nodes to track
- `INTEREST_LEAF_TOP_K = 10` — how many leaf nodes to track
- `INTEREST_REFRESH_INTERVAL = 3600 * 6` — re-analyze graph every 6 hours

---

## Component 2: Discovery Scheduler

**File:** `core/discovery_scheduler.py`

### Behavior

Runs as a background `asyncio.create_task` started in `app.py` lifespan.

1. On startup and every `INTEREST_REFRESH_INTERVAL` seconds:
   - Call `graph_interests.py` to get current keyword list
2. On a shorter `DISCOVERY_INTERVAL` timer (default: every 1 hour):
   - For each keyword, call MiniMax web search via existing API
   - For each search result, extract URL + title + snippet
3. Deduplicate: skip any URL already present in the LanceDB index
4. For each new URL, immediately invoke `run_pipeline(url)` in a background task
5. Track in-flight ingestions to avoid duplicates within the same run

### Sources (search per keyword)

| Source | Method |
|--------|--------|
| Web articles | MiniMax web search API |
| Academic papers | arXiv API (`http://export.arxiv.org/api/query?search_query=all:{keyword}&max_results=3`) |
| YouTube | `yt-dlp --default-search "ytsearch3:{keyword}"` + extract video URLs |
| Social news | HN Algolia API + Lobsters API |

### Configuration

- `DISCOVERY_INTERVAL = 3600` — run discovery every 1 hour
- `MAX_URLS_PER_CYCLE = 10` — cap new ingestions per cycle to avoid quota blowup

---

## Component 3: Gap Detection

**File:** `core/gap_detector.py`

### Behavior

Called from `pipeline.py` after enrichment, before writing to vault:

1. Read the enriched note's `entities` field (list of `[[Entity]]` names)
2. Scan existing vault filenames for case-insensitive match of each entity name
3. Any entity not found in vault → add to note's `gap_entities` list
4. If `gap_entities` is non-empty, submit each as a one-shot MiniMax search
5. Search results go directly to pipeline (no queue, no review)

### Output

Appends to note frontmatter:
```yaml
gap_entities: [EntityNotYetInVault1, EntityNotYetInVault2]
```

---

## Component 4: Pipeline Enhancement

**File:** `pipeline.py` (modified)

- After Step 3 (Enrich), call `detect_gaps(note, raw_text)` from `gap_detector.py`
- Pass `gap_entities` list through to Step 4 (Write) so it can be added to frontmatter
- No new endpoints or UI — only background behavior

---

## Data Flow

```
graph_interests.py          discovery_scheduler.py
      │                            │
      └────── keywords ─────────────►│
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
            MiniMax Search                    External APIs
            (web, arXiv, YouTube, HN)          (arXiv, HN, Nitter)
                    │                                 │
                    └──────────┬──────────────────────┘
                               ▼
                       Deduplication
                    (against LanceDB)
                               │
                               ▼
                       run_pipeline(url)
                               │
                               ▼
                    pipeline.py: enrich + write
                               │
                               ▼
                    gap_detector.py: find entities
                               │         not in vault
                               ▼
                    One-shot searches for gaps
                               │
                               ▼
                       Loop back to pipeline
```

---

## Error Handling

- **Search API failure:** log warning, skip that keyword's cycle, retry next interval
- **Ingestion failure:** log error, do not re-queue (avoids infinite loops on broken URLs)
- **Gap detection failure:** log warning, continue pipeline normally — gap detection is best-effort
- **Duplicate ingestion:** LanceDB `exists()` check prevents re-ingesting same URL

---

## Configuration Variables

Add to `.env` / `config.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCOVERY_ENABLED` | `true` | Master switch for autonomous discovery |
| `DISCOVERY_INTERVAL` | `3600` | Seconds between discovery cycles |
| `INTEREST_HUB_TOP_K` | `15` | Number of hub nodes to extract |
| `INTEREST_LEAF_TOP_K` | `10` | Number of leaf nodes to extract |
| `INTEREST_REFRESH_INTERVAL` | `21600` | Seconds before re-analyzing graph |
| `MAX_URLS_PER_CYCLE` | `10` | Max new URLs to ingest per discovery run |

---

## Files to Create

| File | Purpose |
|------|---------|
| `core/graph_interests.py` | Graph scanner + interest extractor |
| `core/discovery_scheduler.py` | Background discovery loop |
| `core/gap_detector.py` | Post-enrichment entity gap finder |

## Files to Modify

| File | Change |
|------|--------|
| `pipeline.py` | Call `detect_gaps()` after enrichment |
| `app.py` | Start `discovery_scheduler` on lifespan startup |
| `config.py` | Add new configuration variables |

---

## Out of Scope (Phase 1)

- Telegram / notification integration
- Review inbox or approval workflow
- Agent-accessible API endpoints
- Obsolescence / confidence scoring (Phase 2+)
- Graph database (Neo4j/FalkorDB) integration (Phase 2+)
- TTS audio briefings (Phase 3+)

---

## Success Criteria

1. After running for 24 hours with an existing vault, at least 5 new notes appear in the vault from autonomous discovery
2. Gap detection successfully triggers at least one follow-up search from a multi-entity note
3. No duplicate notes are created for the same URL
4. System runs without crashes, errors are logged and skipped gracefully
