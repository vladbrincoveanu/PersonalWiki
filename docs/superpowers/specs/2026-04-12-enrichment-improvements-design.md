# Enrichment Improvements — Design Spec

**Date:** 2026-04-12  
**Status:** Approved

## Goal

Extend the existing MiniMax enrichment step to produce three additional pieces of information in the same LLM call: entity wikilinks, figure captions, and a personal context stub. Notes gain an Obsidian graph, inline figure descriptions, and a "Why I Saved This" hook — with no extra API calls and no changes to the ingestion layer.

## Background

The current pipeline extracts PDFs/web pages and produces notes with `title`, `type`, `tags`, `summary`, `key_facts`, `cross_links`, and YAML frontmatter. What's missing:

1. **Entities/wikilinks** — the Obsidian graph is empty; recurring concepts (datasets, institutions, methods, people) have no `[[links]]` and no stub notes to link to.
2. **Personal context** — no section for why the note was saved, leaving no hook for the user or future RAG queries.
3. **Figure captions** — figures are stored as `![[attachments/slug/figure-N.png]]` but without descriptions; the LLM cannot interpret them during RAG.

All three can be resolved from the existing raw text the LLM already receives, with no vision model needed.

## What Changes

### `core/minimax_client.py`

Add three fields to the JSON schema the LLM is asked to produce:

```json
{
  "entities": [
    {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
    {"name": "Tufts University", "slug": "tufts-university", "type": "institution"}
  ],
  "figure_captions": [
    "Policy network and dynamics model architecture overview",
    "Training reward curves across three robot configurations"
  ],
  "why_saved_hint": "Online MBRL with regret guarantees — directly relevant to sample-efficient robot learning."
}
```

- `entities` — recurring concepts, people, institutions, datasets, methods worth linking to entity notes. Slug is the note filename format (lowercase, hyphenated).
- `figure_captions` — one entry per `<!-- image -->` placeholder in the raw text, in order, inferred from surrounding text. Empty list if no figures.
- `why_saved_hint` — one sentence the user can edit; represents a guess at why this was saved.

Fallback (no API key / API error) returns empty lists and empty string for these fields.

### `vault/writer.py`

`write_note()` gains three new behaviours:

**1. Entities section** — emitted after Key Facts:

```markdown
## Entities
[[MIMIC-IV]] · [[Tufts University]] · [[ROC Analysis]]
```

**2. Why I Saved This section** — emitted after Entities:

```markdown
## Why I Saved This
> Online MBRL with regret guarantees — directly relevant to sample-efficient robot learning.

_(edit this)_
```

**3. Figure captions** — `_replace_image_placeholders()` is updated to inject a caption line above each figure wikilink:

```markdown
*Figure 1: Policy network and dynamics model architecture overview.*
![[attachments/slug/figure-1.png]]
```

If `figure_captions` is shorter than the number of figures, remaining figures are left without captions (no error).

### `vault/entities.py` (new file)

Single function: `upsert_entity_notes(entities: list[dict]) -> None`

For each entity, creates a stub note at `NOTES_DIR/<slug>.md` **only if it does not already exist**. Never overwrites.

Stub format:
```markdown
---
title: MIMIC-IV
type: dataset
tags: []
created: 2026-04-12
---

_Not filled in yet._
```

Called from `write_note()` after the main note is written.

## Note Structure (after change)

```markdown
---
title: Online Model-Based Reinforcement Learning for Robot Control
source: https://arxiv.org/pdf/2510.18518
type: paper
tags: [reinforcement learning, robotics, model-based RL]
ingested: 2026-04-12
---

## Summary
...

## Key Facts
- ...

## Entities
[[Online Learning]] · [[Robot Control]] · [[MuJoCo]]

## Why I Saved This
> Online MBRL with regret guarantees — relevant to sample-efficient robot learning.

_(edit this)_

## My Knowledge Says        ← existing cross_links section, unchanged
[[related-note]]

## Raw Extract              ← existing, unchanged
<details>
...
*Figure 1: Policy network and dynamics model overview.*
![[attachments/slug/figure-1.png]]
...
</details>
```

## What Does NOT Change

- `pipeline.py` — no changes
- `ingesters/` — no changes
- YAML frontmatter fields — unchanged (`title`, `source`, `type`, `tags`, `ingested`)
- Dedup logic — unchanged
- MiniMax client setup, API URL, model — unchanged
- `cross_links` / "My Knowledge Says" section — unchanged

## Edge Cases

- **No entities returned:** Entities section is omitted from the note.
- **No figures:** `figure_captions` is empty list, no caption injection attempted.
- **Fewer captions than figures:** Extra figures rendered without captions.
- **Entity stub already exists:** `upsert_entity_notes` skips it — never overwrites user edits.
- **API error / fallback:** All three new fields default to empty; note written without the new sections.
