---
name: mistake-registry
description: Scan MEMORY.md for repeated error patterns (3+ occurrences) and promote them to scoped .claude/rules/. Use when: (1) errors keep recurring across sessions, (2) you want to see which mistakes are most persistent, (3) a pattern deserves a proactive warning rule.
---

# Mistake Registry

> Captures mistakes. Promotes patterns to enforced rules.

## Invocation

```
/mistake-registry          # full scan and report
/mistake-registry --check  # show stats only, no rule proposals
/mistake-registry --force  # re-evaluate all patterns regardless of count
```

## How It Works

### Phase 1: Scan MEMORY.md

Run the memory scanner to extract error-type entries:

```bash
python docs/superpowers/skills/mistake-registry/memory_scanner.py \
  --memory-path ~/.claude/projects/-Users-vladbrincoveanu-Desktop-Startup-personalWiki/memory/MEMORY.md
```

Expected output (JSON):
```json
{
  "clusters": [
    {
      "pattern_key": "http-timeout",
      "error_summary": "Connection timeout after 30s",
      "count": 4,
      "last_seen": "2026-04-14",
      "files": ["src/http/client.py", "services/api.py"],
      "entries": ["<entry_id_1>", "<entry_id_2>", ...]
    }
  ]
}
```

### Phase 2: Score and Rank

Clusters are ranked by `count × recency_weight`. The top clusters are presented.

### Phase 3: Draft Rule Generation

For clusters with 3+ occurrences, generate a draft rule using `rule_parser.py`:

```bash
python docs/superpowers/skills/mistake-registry/rule_parser.py \
  draft \
  --pattern-key "http-timeout" \
  --count 4 \
  --last-seen "2026-04-14" \
  --files "src/http/*.py" "services/*.py"
```

Expected output (draft rule markdown):
```markdown
---
name: http-client-timeout
description: Always add timeout parameter to HTTP client calls
paths:
  - "**/src/http/*.py"
  - "**/services/*.py"
last_triggered: null
---
- Before creating an HTTP client or calling requests.get/post, fetch, or axios,
  always include a timeout parameter
- **Why:** This pattern appeared 4 times in MEMORY.md, last seen 2026-04-14
- **How to apply:** Verify every HTTP call has timeout=(5-30) seconds
```

### Phase 4: Conflict Detection

Before writing any approved rule, check for conflicts:

```bash
python docs/superpowers/skills/mistake-registry/conflict_detector.py \
  --rules-dir ~/.claude/rules \
  --new-rule-path /tmp/draft-http-timeout.md
```

If conflict detected, output:
```
CONFLICT_DETECTED: http-client-timeout ↔ prefer-async-http
OPTIONS: [1] Overwrite prefer-async-http [2] Abort [3] Merge
```

### Phase 5: Write Rule

On user approval:

```bash
python docs/superpowers/skills/mistake-registry/rule_parser.py \
  write \
  --rule-path ~/.claude/rules/http-client-timeout.md \
  --draft /tmp/draft-http-timeout.md
```

### Phase 6: Archive Stale Rules

On each invocation, check all rules for 60-day inactivity:

```bash
python docs/superpowers/skills/mistake-registry/rule_updater.py \
  --rules-dir ~/.claude/rules \
  --check-expiration
```

Output for stale rules:
```
STALE: http-client-timeout (last_triggered: 2026-01-15, 72 days ago)
PROPOSE_ARCHIVE? [archive/skip]
```

## Output Format

All commands output JSON to stdout for programmatic consumption:
```json
{
  "status": "success|conflict|stale|error",
  "data": { ... },
  "prompt": "optional prompt for user"
}
```

## Error Handling

- MEMORY.md not found: exit 1 with JSON error
- No error entries found: output `{"status": "success", "data": {"clusters": []}}`
- Rules dir not found: create it automatically before write
- Conflict: do not write, return CONFLICT status with options
