# Four-Track Vault Quality & Retrieval Design

**Date:** 2026-04-15
**Status:** Design — awaiting implementation
**Type:** Architectural refactor

## Problem Statement

The personalWiki vault suffers from three interconnected problems:

1. **No quality gate** — 404s, paywalled content, thin extractions, and off-topic articles enter the vault and pollute retrieval
2. **Discovery is not self-reinforcing** — keyword amplification from notes is absent; the graph grows only from user-provided keywords
3. **All content uses identical storage format** — PDFs, videos, articles, and papers all look the same; LLMs can't reliably parse structure
4. **Retrieval is purely vector-based** — no reranking, no graph-aware traversal; misses semantically related notes

## Scope

**In scope:** Quality gate, discovery amplification, YouTube pipeline, typed retrieval, typed storage templates.
**Out of scope:** Tweet/twitter ingestion (broken, no viable alternative, remove entirely). DespreBursa treated as generic website.

---

## Architecture Overview

Four tracks running in two groups:

- **Core stack (A + B + D):** Web, PDF, News → Quality Gate → Enrichment → Amplification Loop → Typed Vault → Typed Retrieval
- **YouTube track (A + C + D):** YouTube → Video Quality Gate → Priority Scoring → Enrichment → Video Template → Typed Retrieval

All tracks share **Track D** (typed retrieval) as the final layer.

---

## Track A — Quality Gate

**Principle:** Reject bad content before it ever hits enrichment. Fail fast.

### Decision Flow

Every URL discovered by the scheduler passes through 4 sequential checks before enrichment:

| Check | Method | Fail Action |
|-------|--------|-------------|
| 1. HTTP status | HEAD request first (fast) | Skip, log reason, don't retry |
| 2. Content length | After extraction: <500 chars (article) or <200 words (video) | Skip, log reason |
| 3. Paywall/auth | Status 401/403 + content heuristics ("subscribe", "premium", "paywalled") | Skip, add URL to suppression list |
| 4. LLM relevance | Discovery-only: lightweight MiniMax call: *"Does this content match keyword '{keyword}'?"* | Skip, demote keyword |

### LLM Relevance Check — Scope

Only scheduler-discovered URLs go through the LLM relevance check. Manual direct-injects (user picks URL themselves) skip this step — user intent is trusted.

If the same keyword produces 3+ LLM "off-topic" responses → suppress that keyword (score < -5).

### Implementation Location

New module: `core/quality_gate.py`. Integration point: `pipeline.py` stage 0 (before Extract), gated behind a `QualityGate` class with a `check(url, raw_text, keyword)` method returning `Pass | Fail(reason)`.

---

## Track B — Discovery Amplification Loop

**Principle:** Good notes beget more good notes. Each quality note that enters the vault feeds new keywords back into the discovery pool.

### Flow

1. Note written to vault after enrichment
2. MiniMax extracts 3-5 new candidate keywords from note content
3. Candidate keywords merged into keyword pool (graph + manual)
4. Next discovery cycle uses expanded pool
5. Cycle repeats

### Amplification Depth

Multi-hop amplification allowed. Each hop increases semantic distance from the root keyword (user's manual keywords). **Distance cutoff:** stop amplification if semantic similarity to any root keyword drops below threshold.

### Cycle Detection

- Track `url→keyword` lineage — if a URL was already discovered via keyword X, don't re-suggest via keyword extracted from that URL
- Keywords extracted from notes degrade over discovery cycles if they produce off-topic results

### Keyword Scoring

| Signal | Score Delta |
|--------|-------------|
| Successful ingest from this keyword | +1 |
| Track A rejection | -2 |
| LLM "off-topic" (×3, leading to suppression) | -5 |
| Suppression threshold | score < -5 |

### Echo Chamber Guard

Every 5th discovery cycle, inject 1-2 random keywords from a broader pool (trending tech topics, general interest) to find content outside the current graph. Low frequency, high upside — prevents tunnel vision.

### Discovery Sources

- arXiv (academic papers)
- Hacker News (Algolia API)
- MiniMax web search (function-calling with regex URL fallback)
- Generic web crawl via Crawl4AI (all websites, no special-casing)

Note: DespreBursa is treated as a generic website. No special crawler rules.

---

## Track C — YouTube Pipeline (Parallel)

**Principle:** Video content is prioritized by relevance, quality-gated by transcript availability, and stored in a video-specific template.

### Video Quality Gate

Same Track A checks, with video-specific thresholds:
- Transcript length <200 words → reject (auto-captions too thin, no retry as stub)
- No transcript available after all 4 fallback tiers → store as stub note with video metadata only

### Video Priority Scoring

Priority score = weighted sum of:
- **Topic match** — keyword overlap with user interests (primary weight)
- **Recency** — newer videos weighted higher (secondary)
- **Engagement** — views/likes as tertiary signal

High-priority videos queued first for ingestion.

### Video Template

```markdown
---
title: "Video Title"
source: https://youtube.com/watch?v=...
type: video
tags: [tag1, tag2]
channel: ChannelName
duration: MM:SS
ingested: YYYY-MM-DD
---

## Timestamped Chapters
- [00:00] Chapter 1
- [01:23] Chapter 2

## Key Quotes
> "quoted text from video" — Speaker

## Summary
...

## Topics Covered
- topic 1
- topic 2

## Transcript (Selected Sections)
[Collapsible full transcript or key sections]

## Why I Saved This
> personal hook...
```

---

## Track D — Typed Retrieval Layer

**Principle:** Shared retrieval backbone for all content types. Better retrieval = better LLM answers.

### Retrieval Stack

```
Query → Vector Search (LanceDB top-K)
      → Cross-Encoder Rerank (cross-re score against query)
      → Graph Transitive Hops (follow wikilinks, 1-2 hops)
      → Final Ranked Results
```

### Cross-Encoder Reranking

A lightweight cross-encoder model re-ranks top-K vector results against the query. Adds ~200-500ms latency but significantly improves retrieval accuracy. Top-K from LanceDB (e.g., top 20) reranked to top 5-10 final results.

### Graph Transitive Hops

If note A links to note B and note B links to note C, a query matching A also returns B and C (1-2 hop transitive closure). Only applied to notes with existing wikilinks. Doesn't affect notes without links.

### Type-Specific Templates

Every content type uses a distinct note template. LLM knows where to look for structured facts.

| Type | Template sections |
|------|-------------------|
| article | Summary (3 sentences), Key Facts, Entities with slugs, Why I Saved This, Raw Extract (collapsible) |
| paper | TL;DR, Method/Architecture, Key Findings, Benchmarks table, Related Work links |
| video | Timestamped chapters, Key Quotes, Speaker/Channel, Transcript (collapsible), Topics covered |

**Migration:** Existing notes without type-specific formatting are updated lazily (on next enrichment pass) or via a background migration script.

---

## Summary: Decision Log

| Decision | Choice |
|----------|--------|
| LLM relevance check scope | Discovery-only (manual direct-injects skip) |
| Amplification depth | Multi-hop, tethered to root keywords, distance cutoff |
| Echo chamber guard | Yes — every 5th cycle random explore keyword |
| Discovery sources | arXiv + HN + MiniMax search + generic web (no DespreBursa special case) |
| Tweet track | Removed (Nitter broken, no viable replacement) |
| DespreBursa | Generic website — no special crawler rules |
| Reranking method | Cross-encoder |
| Typed templates | Per content type (article, paper, video) |
| Graph hops | 1-2 transitive hops, wikilink-based |

---

## Implementation Order

1. **Track A** (quality gate) — new `core/quality_gate.py`, integrated into `pipeline.py`
2. **Track D** (typed retrieval + rerank) — modify `core/vector_store.py`, add rerank class, define typed templates
3. **Track B** (amplification loop) — extend `core/discovery_scheduler.py` with keyword extraction + scoring + cycle detection
4. **Track C** (YouTube) — extend `ingesters/youtube.py` with priority scoring + video template
5. **Note migration** — background script to re-enrich existing notes with typed templates

---

## Files Likely to Change

| File | Change |
|------|--------|
| `core/quality_gate.py` | New — Track A quality gate |
| `core/discovery_scheduler.py` | Track B amplification loop, keyword extraction, scoring |
| `core/vector_store.py` | Track D rerank + graph hops |
| `core/minimax_client.py` | May need lightweight relevance check prompt |
| `ingesters/youtube.py` | Track C video quality gate + priority scoring + video template |
| `pipeline.py` | Integrate quality gate as stage 0 |
| `vault/writer.py` | Typed note templates per content type |
| `ingesters/web.py` | Already using Crawl4AI with `fit_markdown=True` (confirmed) |
| `docs/superpowers/specs/this file` | Design spec |
