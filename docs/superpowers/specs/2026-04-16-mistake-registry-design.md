# Mistake Registry — Design

**Date:** 2026-04-16
**Status:** Approved
**Author:** Vlad Brincoveanu

---

## Overview

**Name:** `mistake-registry`

**Purpose:** Scans MEMORY.md for repeated error patterns (3+ occurrences) and promotes the most persistent ones into scoped `.claude/rules/` files that fire active warnings before high-risk code generation.

**Core insight:** The error-capture hook already saves mistakes. This skill adds the judgment layer — it reads those saved mistakes, counts recurrences, and asks the user which ones deserve to become enforced rules.

**Invocation:** `/mistake-registry` — on demand, or after a session where multiple errors occurred.

---

## Architecture

```
MEMORY.md
  (error-capture hook writes failures here)

      ↓ (scanned by mistake-registry skill)

mistake-registry skill
  ├── Parser:    extracts error patterns, command context, file/module
  ├── Counter:   aggregates occurrences across sessions
  ├── Scorer:    ranks by recurrence frequency + recency
  ├── Searcher:  semantically searches .claude/rules/ for conflicts
  └── Rule Generator: produces .claude/rules/<name>.md files

      ↓ (on user approval)

.claude/rules/<name>.md
  (scoped rule — loads automatically when Claude Code touches matching files)
```

### Components

| Component | Type | Description |
|-----------|------|-------------|
| `error-capture` hook | Existing | Saves failed commands, error output, timestamp, file context to MEMORY.md |
| `mistake-registry` skill | New | Scanner + rule generator + conflict checker |
| `.claude/rules/` | New | Scoped prevention rules loaded by Claude Code on file match |

---

## Data Flow

### Step 1: Capture (existing hook)

The `error-capture` hook (from `self-improving-agent`) monitors command output for errors. On detection, it appends a structured entry to MEMORY.md:

```markdown
---
name: error-http-timeout
type: error
command: "curl https://api.example.com/data"
error: "Connection timeout after 30s"
file: "src/http/client.py"
timestamp: 2026-04-16
---
```

### Step 2: Scan (skill invocation)

On `/mistake-registry` invocation, the skill:

1. **Reads** all MEMORY.md entries with `type: error`
2. **Clusters** similar errors by pattern key (e.g., "timeout", "missing await", "undefined var")
3. **Counts** occurrences per cluster
4. **Ranks** by frequency × recency

### Step 3: Propose (3+ threshold)

For clusters with **3 or more** occurrences, the skill generates a draft scoped rule and shows:

```
Pattern: HTTP client missing timeout (seen 4 times, last: 2026-04-14)

Draft rule:
---
name: http-client-timeout
description: Always add timeout parameter to HTTP client calls
paths:
  - "**/*.py"
  - "**/http*.ts"
last_triggered: null
---
- Before creating an HTTP client or calling requests.get/post, fetch, or axios,
  always include a timeout parameter
- Why: Past errors in this project had silent hangs from missing timeouts

Approve? [yes/edit/no]
```

### Step 4: Conflict Resolution (before write)

Before writing any approved rule, the skill semantically searches existing `.claude/rules/`. If a contradiction is detected (e.g., new rule says "always use sync" but existing rule says "prefer async"), it pauses and prompts:

> "Rule 'http-client-timeout' contradicts existing rule 'prefer-async-http'. Choose:
> 1. Overwrite 'prefer-async-http'
> 2. Abort this rule
> 3. Merge both into a combined rule"

### Step 5: Write

Approved rules land in `.claude/rules/<slug>.md`. Claude Code automatically loads rules whose `paths` glob matches the files being edited.

### Step 6: Trigger Tracking

Every time a rule's glob matches a file being touched, the rule's `last_triggered` field is updated to today's date.

---

## Rule Template

```markdown
---
name: <slug>
description: <one-line summary>
paths:
  - "<glob>"      # file patterns that activate this rule
  - "<glob>"
last_triggered: <YYYY-MM-DD>   # auto-updated on each activation
---
- <prescription 1>
- <prescription 2>

**Why:** <explanation drawn from memory patterns>

**How to apply:** <checklist or guidance for this specific pattern>
```

---

## Expiration / Decay

Rules that have not been triggered in **60 days** are flagged for archiving.

On `/mistake-registry` run, the skill checks `last_triggered` on all rules:
- If `last_triggered` is more than 60 days ago, propose archiving
- Archiving prompt: "Rule 'X' hasn't fired in 72 days. Archive it? [archive/skip]"

Archiving moves the rule to `.claude/rules/.archived/<slug>.md` — still readable but no longer active.

---

## Integration with Existing Skills

| Skill | Relationship |
|-------|-------------|
| `self-improving-agent` | Shares `error-capture` hook infrastructure; rules generated are surfaced as promotion candidates in `/si:review` |
| `systematic-debugging` | Errors are already being saved; mistake-registry reads them for pattern analysis |
| `test-driven-development` | Rules are additional guardrails, not replacements for TDD |
| `verification-before-completion` | Verification failures saved to MEMORY.md feed into the mistake registry |

---

## Invocation

```
/mistake-registry          # full scan and report
/mistake-registry --check  # check only, show stats without proposing rules
/mistake-registry --force  # re-evaluate all patterns regardless of count
```

---

## What Gets Committed

1. `docs/superpowers/skills/mistake-registry/SKILL.md` — the skill file
2. This design doc (already committed)
3. No rules are committed automatically — user approval gates each rule

---

## Open Questions (resolved)

| Question | Resolution |
|----------|------------|
| Trigger threshold? | 3 occurrences minimum |
| Who approves rules? | User approves each before write |
| Conflict with existing rules? | Prompt user: overwrite, abort, or merge |
| Stale rules? | 60-day expiration with archive proposal |

---

## Next Step

Invoke `superpowers:writing-plans` to create the implementation plan.
