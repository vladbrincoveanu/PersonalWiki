# VKE Simplified Paper Processing Design

**Date:** 2026-04-07
**Status:** Approved

## Overview

Simplify the VKE wiki output to produce exactly 2 files per ingested source: a raw annotated page and a verified claims page. Make annotations use Obsidian callout syntax throughout.

---

## File Structure

```
wiki/
├── raw/{source-id}.md          # Full content with visual annotations
└── verified/{source-id}.md      # Only verified claims with sources
```

### Raw Page (`/raw/{id}.md`)
- Full original text/content, paragraph-by-paragraph (not sentence-split)
- Annotations via Obsidian callouts marking claim status
- Human-readable, suitable for direct review

### Verified Page (`/verified/{id}.md`)
- Only claims with >60% verification confidence
- Each claim includes:
  - Verified statement
  - Source URLs found during verification
  - Reference to original source
- Organized by topic/section

---

## Claim Classification

### States
| State | Criteria | Visual (Callout) | Score |
|-------|----------|------------------|-------|
| VERIFIED | >60% confidence, verifiable | `> [!VERIFIED]` | 0.6-1.0 |
| UNVERIFIED | Derivative claim, needs human check | `> [!UNVERIFIED]` | N/A |
| CANNOT_VERIFY | No primary source available | `> [!CANNOT_VERIFY]` | 0.5 (default) |

### Verification Logic
1. **Trusted source** (SEC filings, govt, official) → Auto-VERIFIED if >60%
2. **Derivative** (article citing company data) → Verify against primary source
3. **No primary possible** (experimental results) → CANNOT_VERIFY, 50% score, needs human

---

## Obsidian Callout Format

### Raw Page Annotations
```markdown
> [!VERIFIED]
> Claim text here with **bold** for key facts.

> [!UNVERIFIED]
> This claim cites company X data - needs verification against SEC filing.

> [!CANNOT_VERIFY]
> Experimental result from paper - no external source available. Needs human review.
```

### Verified Page Format
```markdown
## Verified Claims

### Claim 1
**Statement:** The paper was published at SOSP 2023.

**Sources:**
- https://arxiv.org/abs/2309.06180
- https://doi.org/10.48550/arXiv.2309.06180

**Original Source:** arXiv paper abstract
```

---

## Verification Confidence Rules

- **>80%** → Highly confident, auto-verify
- **60-80%** → Confident, include in verified
- **<60%** → Requires human review or mark unverified
- **No source available** → CANNOT_VERIFY, 50% default, needs human

---

## Data Flow

```
Ingest URL
    ↓
Fetch Content (GenericUrlClient)
    ↓
Extract Claims (LlmClient)
    ↓
Classify Claims
    ├── Trusted source? → Mark VERIFIED (>60%)
    ├── Derivative? → Check against primary source
    └── No source? → Mark CANNOT_VERIFY
    ↓
Write Raw Page (with Obsidian callouts)
    ↓
Write Verified Page (only >60% claims + sources)
```

---

## Implementation Tasks

1. Modify WikiGenerator to produce two file types
2. Update VerifyAgent claim classification logic
3. Add Obsidian callout formatting
4. Add source linking to verified claims
5. Update claim status enum (add CANNOT_VERIFY)
6. Update database schema if needed for new statuses

---

## Example Output

### Raw Page (`raw/arxiv-2309.06180.md`)
```markdown
# Efficient Memory Management for LLM Serving with PagedAttention

**URL:** https://arxiv.org/abs/2309.06180
**Type:** academic paper
**Fetched:** 2026-04-07

## Content

> [!CANNOT_VERIFY]
> PagedAttention achieves 2-4x throughput improvement over existing systems.

> [!VERIFIED]
> The paper was published at SOSP 2023.

> [!UNVERIFIED]
> vLLM is used in production at major tech companies - needs verification.
```

### Verified Page (`verified/arxiv-2309.06180.md`)
```markdown
# Verified Claims: PagedAttention Paper

**Source:** https://arxiv.org/abs/2309.06180
**Verified:** 2026-04-07

## Claims

### Published at SOSP 2023
**Statement:** The paper was published at SOSP 2023.

**Confidence:** 95%

**Sources:**
- https://arxiv.org/abs/2309.06180

---

### Authors
**Statement:** Authors include Woosuk Kwon, Zhuohan Li, et al.

**Confidence:** 100%

**Sources:**
- https://arxiv.org/abs/2309.06180
```

---

## Notes

- Entity pages removed (too granular, hard to maintain)
- All output uses Obsidian-compatible markdown
- Wiki links only when connecting to other verified sources
