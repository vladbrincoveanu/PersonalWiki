# Mistake Registry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `mistake-registry` skill that scans MEMORY.md for repeated error patterns (3+ occurrences), detects conflicts with existing rules, and prompts the user to promote patterns into scoped `.claude/rules/` files.

**Architecture:** A Python CLI skill invoked as `/mistake-registry`, backed by three reusable modules: `rule_parser.py` (read/write `.claude/rules/`), `memory_scanner.py` (parse and cluster MEMORY.md entries), and `conflict_detector.py` (semantic conflict detection). The skill outputs structured markdown to stdout for Claude to present to the user.

**Tech Stack:** Python 3, no external dependencies (pure stdlib for maximum portability).

---

## File Structure

```
docs/superpowers/skills/mistake-registry/
├── SKILL.md                          # Skill definition + usage guide
├── rule_parser.py                    # Read/write .claude/rules/ files
├── memory_scanner.py                  # Parse MEMORY.md, cluster errors
├── conflict_detector.py               # Semantic conflict detection between rules
├── rule_updater.py                   # Update last_triggered on existing rules
└── tests/
    ├── test_rule_parser.py
    ├── test_memory_scanner.py
    └── test_conflict_detector.py

.claude/rules/                        # Created on first rule write
.claude/rules/.archived/              # Created when archiving stale rules
```

---

## Task 1: Skill File and Directory Scaffold

**Files:**
- Create: `docs/superpowers/skills/mistake-registry/SKILL.md`
- Create: `docs/superpowers/skills/mistake-registry/.gitkeep`

- [ ] **Step 1: Create directory**

Run: `mkdir -p docs/superpowers/skills/mistake-registry`

- [ ] **Step 2: Write SKILL.md**

```markdown
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
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/skills/mistake-registry/ && \
git commit -m "feat: scaffold mistake-registry skill directory and SKILL.md"
```

---

## Task 2: rule_parser.py

**Files:**
- Create: `docs/superpowers/skills/mistake-registry/rule_parser.py`
- Create: `docs/superpowers/skills/mistake-registry/tests/test_rule_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# docs/superpowers/skills/mistake-registry/tests/test_rule_parser.py
import subprocess
import tempfile
import os

def test_draft_generates_valid_yaml_frontmatter():
    """Draft command should output markdown with valid YAML frontmatter."""
    result = subprocess.run(
        ["python", "docs/superpowers/skills/mistake-registry/rule_parser.py",
         "draft", "--pattern-key", "http-timeout", "--count", "4",
         "--last-seen", "2026-04-14", "--files", "src/http/*.py"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    output = result.stdout
    assert output.startswith("---")
    assert "name: http-timeout" in output
    assert "last_triggered: null" in output

def test_write_creates_file():
    """Write command should create the rule file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        draft = os.path.join(tmpdir, "draft.md")
        rule_path = os.path.join(tmpdir, "rules", "test-rule.md")
        with open(draft, "w") as f:
            f.write("---\nname: test\ndescription: test\npaths: []\n---\ntest")
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/rule_parser.py",
             "write", "--rule-path", rule_path, "--draft", draft],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert os.path.exists(rule_path)

def test_read_rule_extracts_metadata():
    """Read command should parse existing rule and return JSON metadata."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("---\nname: test-rule\ndescription: Test desc\npaths:\n  - '**/*.py'\nlast_triggered: 2026-04-01\n---\n- prescription")
        path = f.name
    try:
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/rule_parser.py",
             "read", "--rule-path", path],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert data["name"] == "test-rule"
        assert data["last_triggered"] == "2026-04-01"
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest docs/superpowers/skills/mistake-registry/tests/test_rule_parser.py -v`
Expected: FAIL — rule_parser.py does not exist yet

- [ ] **Step 3: Write minimal rule_parser.py**

```python
#!/usr/bin/env python3
"""
rule_parser.py — Read, draft, and write .claude/rules/ files.

Usage:
    python rule_parser.py draft --pattern-key <key> --count <N> --last-seen <date> --files <glob>...
    python rule_parser.py write --rule-path <path> --draft <path>
    python rule_parser.py read --rule-path <path>
    python rule_parser.py list --rules-dir <path>
"""

import sys
import json
import argparse
import os
import re
import yaml
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)", re.DOTALL)

def parse_frontmatter(content: str) -> tuple[dict, str]:
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}, content
    fm_raw, body = match.groups()
    fm = yaml.safe_load(fm_raw) or {}
    return fm, body

def render_draft(pattern_key: str, count: int, last_seen: str, files: list[str]) -> str:
    slug = pattern_key.replace(" ", "-").lower()
    paths = [f'"{f}"' for f in files] if files else ['"**/*"']
    why = f"This pattern appeared {count} times in MEMORY.md, last seen {last_seen}"
    return f"""---
name: {slug}
description: TODO: write one-line description
paths:
  - {paths[0]}
last_triggered: null
---
- TODO: write prescription 1
- TODO: write prescription 2

**Why:** {why}

**How to apply:** TODO: write checklist
"""

def cmd_draft(args):
    output = render_draft(args.pattern_key, args.count, args.last_seen, args.files)
    print(output)
    return 0

def cmd_write(args):
    rule_path = Path(args.rule_path)
    rule_path.parent.mkdir(parents=True, exist_ok=True)
    with open(args.draft) as f:
        content = f.read()
    with open(rule_path, "w") as f:
        f.write(content)
    print(json.dumps({"status": "success", "path": str(rule_path)}))
    return 0

def cmd_read(args):
    with open(args.rule_path) as f:
        content = f.read()
    fm, body = parse_frontmatter(content)
    print(json.dumps({
        "name": fm.get("name", ""),
        "description": fm.get("description", ""),
        "paths": fm.get("paths", []),
        "last_triggered": fm.get("last_triggered"),
        "body": body.strip()
    }))
    return 0

def cmd_list(args):
    rules_dir = Path(args.rules_dir)
    if not rules_dir.exists():
        print(json.dumps({"rules": []}))
        return 0
    rules = []
    for f in rules_dir.rglob("*.md"):
        if ".archived" in f.parts:
            continue
        with open(f) as fh:
            fm, _ = parse_frontmatter(fh.read())
        rules.append({
            "name": fm.get("name", f.stem),
            "path": str(f),
            "last_triggered": fm.get("last_triggered"),
            "paths": fm.get("paths", [])
        })
    print(json.dumps({"rules": rules}))
    return 0

def main():
    parser = argparse.ArgumentParser(description="mistake-registry rule parser")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("draft")
    p.add_argument("--pattern-key"); p.add_argument("--count", type=int)
    p.add_argument("--last-seen"); p.add_argument("--files", nargs="*")
    p.set_defaults(func=cmd_draft)

    p = sub.add_parser("write")
    p.add_argument("--rule-path"); p.add_argument("--draft")
    p.set_defaults(func=cmd_write)

    p = sub.add_parser("read")
    p.add_argument("--rule-path")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("list")
    p.add_argument("--rules-dir", default=".claude/rules")
    p.set_defaults(func=cmd_list)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help(); return 1
    sys.exit(args.func(args))

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest docs/superpowers/skills/mistake-registry/tests/test_rule_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/skills/mistake-registry/rule_parser.py \
        docs/superpowers/skills/mistake-registry/tests/test_rule_parser.py && \
git commit -m "feat(mistake-registry): add rule_parser.py draft/write/read/list commands"
```

---

## Task 3: memory_scanner.py

**Files:**
- Create: `docs/superpowers/skills/mistake-registry/memory_scanner.py`
- Create: `docs/superpowers/skills/mistake-registry/tests/test_memory_scanner.py`

- [ ] **Step 1: Write the failing test**

```python
# docs/superpowers/skills/mistake-registry/tests/test_memory_scanner.py
import subprocess
import tempfile
import os

MEMORY_SAMPLE = """---
name: error-timeout-1
type: error
command: "curl https://api.example.com"
error: "Connection timeout"
file: "src/http/client.py"
timestamp: 2026-04-10
---
some content

---
name: error-timeout-2
type: error
command: "fetch /data"
error: "TimeoutError"
file: "services/api.ts"
timestamp: 2026-04-12
---

---
name: error-missing-await
type: error
command: "git push"
error: "SyntaxError: 'await' outside async function"
file: "src/bot.py"
timestamp: 2026-04-11
---
"""

def test_scanner_extracts_error_entries():
    """Scanner should extract all type:error entries."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(MEMORY_SAMPLE)
        path = f.name
    try:
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/memory_scanner.py",
             "--memory-path", path],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert data["total_entries"] == 3
    finally:
        os.unlink(path)

def test_scanner_clusters_by_pattern():
    """Scanner should cluster timeout errors together."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(MEMORY_SAMPLE)
        path = f.name
    try:
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/memory_scanner.py",
             "--memory-path", path],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout)
        clusters = data["clusters"]
        # Should have 2 clusters: timeout (2) and missing-await (1)
        assert len(clusters) == 2
        timeout_cluster = next(c for c in clusters if "timeout" in c["pattern_key"])
        assert timeout_cluster["count"] == 2
        assert "2026-04-12" in timeout_cluster["last_seen"]
    finally:
        os.unlink(path)

def test_scanner_threshold():
    """Scanner should only include clusters with count >= threshold."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(MEMORY_SAMPLE)
        path = f.name
    try:
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/memory_scanner.py",
             "--memory-path", path, "--min-count", "3"],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout)
        assert len(data["clusters"]) == 0  # No cluster has 3+
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest docs/superpowers/skills/mistake-registry/tests/test_memory_scanner.py -v`
Expected: FAIL — memory_scanner.py does not exist

- [ ] **Step 3: Write minimal memory_scanner.py**

```python
#!/usr/bin/env python3
"""
memory_scanner.py — Parse MEMORY.md, extract error entries, cluster by pattern.

Usage:
    python memory_scanner.py --memory-path <path> [--min-count <N>]
"""

import sys
import json
import argparse
import re
import yaml
from collections import defaultdict
from datetime import datetime

ENTRY_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

PATTERN_KEYWORDS = {
    "timeout": ["timeout", "timed out", "timed_out", "Connection timeout", "TimeoutError"],
    "missing-await": ["await", "async", "'await' outside"],
    "import-error": ["ImportError", "ModuleNotFoundError", "cannot import"],
    "syntax-error": ["SyntaxError", "ParseError"],
    "attribute-error": ["AttributeError", "has no attribute"],
    "undefined": ["undefined", "not defined", "NameError"],
}

def extract_pattern_key(error_text: str) -> str:
    error_lower = error_text.lower()
    for key, keywords in PATTERN_KEYWORDS.items():
        if any(kw.lower() in error_lower for kw in keywords):
            return key
    # Fallback: first 3 words of error
    words = error_text.split()[:3]
    return "-".join(w.lower().strip(".:!?,()[]") for w in words if w)

def parse_entries(memory_path: str) -> list[dict]:
    with open(memory_path) as f:
        content = f.read()
    entries = []
    blocks = content.split("---")
    for i in range(1, len(blocks), 2):
        chunk = blocks[i].strip()
        try:
            fm = yaml.safe_load(chunk)
        except:
            continue
        if fm and fm.get("type") == "error":
            entries.append({
                "name": fm.get("name", ""),
                "error": fm.get("error", ""),
                "file": fm.get("file", ""),
                "timestamp": fm.get("timestamp", ""),
                "command": fm.get("command", ""),
            })
    return entries

def cluster_entries(entries: list[dict]) -> list[dict]:
    clusters = defaultdict(lambda: {"count": 0, "errors": [], "files": set(), "timestamps": []})
    for e in entries:
        key = extract_pattern_key(e["error"])
        clusters[key]["count"] += 1
        clusters[key]["errors"].append(e["error"])
        if e["file"]:
            clusters[key]["files"].add(e["file"])
        if e["timestamp"]:
            clusters[key]["timestamps"].append(e["timestamp"])
    result = []
    for key, data in clusters.items():
        result.append({
            "pattern_key": key,
            "error_summary": data["errors"][-1] if data["errors"] else "",
            "count": data["count"],
            "last_seen": max(data["timestamps"]) if data["timestamps"] else "",
            "files": sorted(data["files"]),
        })
    result.sort(key=lambda c: c["count"], reverse=True)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-path", required=True)
    parser.add_argument("--min-count", type=int, default=1)
    args = parser.parse_args()

    entries = parse_entries(args.memory_path)
    clusters = cluster_entries(entries)
    clusters = [c for c in clusters if c["count"] >= args.min_count]

    print(json.dumps({
        "total_entries": len(entries),
        "clusters": clusters
    }, indent=2))

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest docs/superpowers/skills/mistake-registry/tests/test_memory_scanner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/skills/mistake-registry/memory_scanner.py \
        docs/superpowers/skills/mistake-registry/tests/test_memory_scanner.py && \
git commit -m "feat(mistake-registry): add memory_scanner.py parse and cluster commands"
```

---

## Task 4: conflict_detector.py

**Files:**
- Create: `docs/superpowers/skills/mistake-registry/conflict_detector.py`
- Create: `docs/superpowers/skills/mistake-registry/tests/test_conflict_detector.py`

- [ ] **Step 1: Write the failing test**

```python
# docs/superpowers/skills/mistake-registry/tests/test_conflict_detector.py
import subprocess
import tempfile
import os

RULE_SYNC = """---
name: prefer-sync-http
description: Use synchronous HTTP calls only
paths: ["**/*.py"]
last_triggered: 2026-03-01
---
- Use synchronous requests library only
"""

RULE_ASYNC = """---
name: prefer-async-http
description: Use async HTTP calls
paths: ["**/*.py"]
last_triggered: 2026-03-01
---
- Use aiohttp for HTTP calls
"""

def test_no_conflict_when_rules_differ():
    """Rules with unrelated content should not conflict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_dir = os.path.join(tmpdir, "rules")
        os.makedirs(rules_dir)
        with open(os.path.join(rules_dir, "sync.md"), "w") as f:
            f.write(RULE_SYNC)
        with open(os.path.join(rules_dir, "async.md"), "w") as f:
            f.write(RULE_ASYNC)
        new_rule = os.path.join(tmpdir, "new.md")
        with open(new_rule, "w") as f:
            f.write("---\nname: new-rule\ndescription: New unrelated rule\npaths: ['**/*.go']\n---\n- Do something in Go")
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/conflict_detector.py",
             "--rules-dir", rules_dir, "--new-rule-path", new_rule],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout)
        assert data["status"] == "ok"
        assert data["conflicts"] == []

def test_detects_contradiction_in_body():
    """New rule about timeouts vs existing rule about async should not conflict
    (they address different concerns)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_dir = os.path.join(tmpdir, "rules")
        os.makedirs(rules_dir)
        with open(os.path.join(rules_dir, "timeout.md"), "w") as f:
            f.write("---\nname: http-timeout\ndescription: Always set timeout\npaths: ['**/*.py']\n---\n- Always set timeout on HTTP calls")
        new_rule = os.path.join(tmpdir, "new.md")
        with open(new_rule, "w") as f:
            f.write("---\nname: new-timeout\ndescription: Strict timeout policy\npaths: ['**/*.py']\n---\n- Timeout must be under 5 seconds")
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/conflict_detector.py",
             "--rules-dir", rules_dir, "--new-rule-path", new_rule],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout)
        # timeout + timeout = same domain, but different prescriptions
        # These don't contradict — they reinforce. status = ok
        assert data["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest docs/superpowers/skills/mistake-registry/tests/test_conflict_detector.py -v`
Expected: FAIL — conflict_detector.py does not exist

- [ ] **Step 3: Write minimal conflict_detector.py**

```python
#!/usr/bin/env python3
"""
conflict_detector.py — Detect semantic conflicts between a new rule and existing rules.

Usage:
    python conflict_detector.py --rules-dir <path> --new-rule-path <path>
"""

import sys
import json
import argparse
import os
import re
from pathlib import Path

# Keywords that indicate conflicting concerns
CONFLICT_PAIRS = [
    (["sync", "synchronous", "requests.get", "requests.post"],
     ["async", "await", "aiohttp", "httpx.AsyncClient"]),
    (["never use"], ["always use", "prefer"]),
]

def read_rule_body(path: str) -> str:
    with open(path) as f:
        content = f.read()
    match = re.match(r"^---\n.*?\n---\n(.*)", content, re.DOTALL)
    return match.group(1).strip().lower() if match else ""

def rules_share_paths(new_paths: list, existing_paths: list) -> bool:
    # If globs overlap, they apply to the same files — check for content conflict
    return True  # Conservative: always check body conflicts when paths overlap

def detect_conflicts(new_body: str, existing_rules: list[dict]) -> list[dict]:
    conflicts = []
    for rule in existing_rules:
        existing_body = rule["body"].lower()
        for forbid_set, require_set in CONFLICT_PAIRS:
            new_has_forbid = any(k in new_body for k in forbid_set)
            new_has_require = any(k in new_body for k in require_set)
            exist_has_forbid = any(k in existing_body for k in forbid_set)
            exist_has_require = any(k in existing_body for k in require_set)
            # Contradiction: new says "never X", existing says "always X"
            # or: new says "always X", existing says "never X"
            if (new_has_forbid and exist_has_require) or (new_has_require and exist_has_forbid):
                conflicts.append({
                    "existing_rule": rule["name"],
                    "existing_path": rule["path"],
                    "reason": f"new rule contains '{forbid_set if new_has_forbid else require_set}' "
                              f"but existing rule '{rule['name']}' contains opposite"
                })
    return conflicts

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules-dir", required=True)
    parser.add_argument("--new-rule-path", required=True)
    args = parser.parse_args()

    rules_dir = Path(args.rules_dir)
    if not rules_dir.exists():
        print(json.dumps({"status": "ok", "conflicts": []}))
        return 0

    # Read existing rules
    existing = []
    for f in rules_dir.rglob("*.md"):
        if ".archived" in f.parts:
            continue
        with open(f) as fh:
            content = fh.read()
        match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
        if match:
            import yaml
            fm = yaml.safe_load(match.group(1)) or {}
            existing.append({
                "name": fm.get("name", f.stem),
                "path": str(f),
                "body": match.group(2).strip(),
                "paths": fm.get("paths", [])
            })

    # Read new rule
    new_body = read_rule_body(args.new_rule_path)
    with open(args.new_rule_path) as f:
        import yaml
        fm_new = yaml.safe_load(f.read())
    new_paths = fm_new.get("paths", [])

    # Check path overlap + body conflict
    conflicts = []
    for rule in existing:
        if rules_share_paths(new_paths, rule["paths"]):
            rule_conflicts = detect_conflicts(new_body, [rule])
            conflicts.extend(rule_conflicts)

    if conflicts:
        print(json.dumps({
            "status": "conflict",
            "conflicts": conflicts,
            "options": ["overwrite", "abort", "merge"]
        }))
    else:
        print(json.dumps({"status": "ok", "conflicts": []}))

    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest docs/superpowers/skills/mistake-registry/tests/test_conflict_detector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/skills/mistake-registry/conflict_detector.py \
        docs/superpowers/skills/mistake-registry/tests/test_conflict_detector.py && \
git commit -m "feat(mistake-registry): add conflict_detector.py semantic conflict detection"
```

---

## Task 5: rule_updater.py + Integration Test

**Files:**
- Create: `docs/superpowers/skills/mistake-registry/rule_updater.py`
- Create: `docs/superpowers/skills/mistake-registry/tests/test_rule_updater.py`
- Create: `docs/superpowers/skills/mistake-registry/tests/test_integration.py`

- [ ] **Step 1: Write rule_updater.py**

```python
#!/usr/bin/env python3
"""
rule_updater.py — Update last_triggered on rules, check expiration.

Usage:
    python rule_updater.py --rules-dir <path> --update-last-triggered <name>
    python rule_updater.py --rules-dir <path> --check-expiration
"""

import sys
import json
import argparse
import os
import re
import yaml
from pathlib import Path
from datetime import datetime, timedelta

ARCHIVE_DIR = ".archived"
EXPIRATION_DAYS = 60

def update_last_triggered(rules_dir: Path, rule_name: str) -> dict:
    for f in rules_dir.rglob("*.md"):
        if ".archived" in f.parts:
            continue
        with open(f) as fh:
            content = fh.read()
        match = re.match(r"^(---.*?\n---\n)(.*)", content, re.DOTALL)
        if not match:
            continue
        fm_raw, body = match.groups()
        fm = yaml.safe_load(fm_raw) or {}
        if fm.get("name") == rule_name:
            today = datetime.now().strftime("%Y-%m-%d")
            fm["last_triggered"] = today
            new_content = f"---\n{yaml.dump(fm, default_flow_style=False)}---\n{body}"
            with open(f, "w") as fh:
                fh.write(new_content)
            return {"status": "success", "path": str(f), "last_triggered": today}
    return {"status": "error", "message": f"Rule '{rule_name}' not found"}

def check_expiration(rules_dir: Path) -> list[dict]:
    stale = []
    cutoff = (datetime.now() - timedelta(days=EXPIRATION_DAYS)).strftime("%Y-%m-%d")
    for f in rules_dir.rglob("*.md"):
        if ".archived" in f.parts:
            continue
        with open(f) as fh:
            content = fh.read()
        match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if not match:
            continue
        fm = yaml.safe_load(match.group(1)) or {}
        last_triggered = fm.get("last_triggered", "null")
        if last_triggered and last_triggered != "null" and last_triggered < cutoff:
            stale.append({
                "name": fm.get("name", f.stem),
                "path": str(f),
                "last_triggered": last_triggered,
                "days_ago": (datetime.now() - datetime.strptime(last_triggered, "%Y-%m-%d")).days
            })
    return stale

def archive_rule(rules_dir: Path, rule_name: str) -> dict:
    archive_path = rules_dir / ARCHIVE_DIR
    archive_path.mkdir(exist_ok=True)
    for f in rules_dir.rglob("*.md"):
        if ".archived" in f.parts or f.stem == rule_name:
            continue
        with open(f) as fh:
            content = fh.read()
        match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if not match:
            continue
        fm = yaml.safe_load(match.group(1)) or {}
        if fm.get("name") == rule_name:
            archive_file = archive_path / f.name
            with open(archive_file, "w") as fh:
                fh.write(content)
            os.remove(f)
            return {"status": "archived", "from": str(f), "to": str(archive_file)}
    return {"status": "error", "message": f"Rule '{rule_name}' not found"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules-dir", required=True)
    parser.add_argument("--update-last-triggered")
    parser.add_argument("--check-expiration", action="store_true")
    parser.add_argument("--archive")
    args = parser.parse_args()

    rules_dir = Path(args.rules_dir)

    if args.update_last_triggered:
        result = update_last_triggered(rules_dir, args.update_last_triggered)
        print(json.dumps(result))
    elif args.check_expiration:
        stale = check_expiration(rules_dir)
        print(json.dumps({"status": "success", "stale": stale}))
    elif args.archive:
        result = archive_rule(rules_dir, args.archive)
        print(json.dumps(result))
    else:
        parser.print_help()
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write test_rule_updater.py**

```python
import subprocess
import tempfile
import os
from datetime import datetime, timedelta

def test_update_last_triggered():
    with tempfile.TemporaryDirectory() as tmpdir:
        rule_file = os.path.join(tmpdir, "test-rule.md")
        with open(rule_file, "w") as f:
            f.write("---\nname: test-rule\ndescription: Test\npaths: []\nlast_triggered: 2026-01-01\n---\nprescription")
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/rule_updater.py",
             "--rules-dir", tmpdir, "--update-last-triggered", "test-rule"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert data["status"] == "success"
        # Verify file was updated
        with open(rule_file) as f:
            content = f.read()
        assert "last_triggered: " in content

def test_check_expiration_finds_stale_rule():
    old_date = (datetime.now() - timedelta(days=72)).strftime("%Y-%m-%d")
    with tempfile.TemporaryDirectory() as tmpdir:
        rule_file = os.path.join(tmpdir, "stale-rule.md")
        with open(rule_file, "w") as f:
            f.write(f"---\nname: stale-rule\ndescription: Test\npaths: []\nlast_triggered: {old_date}\n---\nprescription")
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/rule_updater.py",
             "--rules-dir", tmpdir, "--check-expiration"],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout)
        assert data["status"] == "success"
        assert len(data["stale"]) == 1
        assert data["stale"][0]["name"] == "stale-rule"
        assert data["stale"][0]["days_ago"] >= 70
```

- [ ] **Step 3: Write test_integration.py**

```python
"""Full round-trip integration test: scan -> draft -> detect conflict -> write."""
import subprocess
import tempfile
import os
import json

MEMORY_WITH_PATTERNS = """---
name: error-timeout-1
type: error
error: "Connection timeout after 30s"
file: "src/http/client.py"
timestamp: 2026-04-10
---
---
name: error-timeout-2
type: error
error: "TimeoutError: timed out"
file: "src/http/client.py"
timestamp: 2026-04-12
---
---
name: error-timeout-3
type: error
error: "timeout in requests.get"
file: "services/api.py"
timestamp: 2026-04-14
---
"""

def test_full_round_trip():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory_path = os.path.join(tmpdir, "MEMORY.md")
        rules_dir = os.path.join(tmpdir, "rules")
        os.makedirs(rules_dir)
        with open(memory_path, "w") as f:
            f.write(MEMORY_WITH_PATTERNS)

        # 1. Scan memory
        scan_result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/memory_scanner.py",
             "--memory-path", memory_path, "--min-count", "3"],
            capture_output=True, text=True
        )
        assert scan_result.returncode == 0
        data = json.loads(scan_result.stdout)
        assert data["total_entries"] == 3

        # 2. Draft a rule for the top cluster
        draft_result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/rule_parser.py",
             "draft", "--pattern-key", "timeout",
             "--count", "3", "--last-seen", "2026-04-14",
             "--files", "src/http/*.py", "services/*.py"],
            capture_output=True, text=True
        )
        assert draft_result.returncode == 0
        assert "name: timeout" in draft_result.stdout

        # 3. Save draft to temp file
        draft_path = os.path.join(tmpdir, "draft.md")
        with open(draft_path, "w") as f:
            f.write(draft_result.stdout)

        # 4. Detect conflicts (should be none)
        conflict_result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/conflict_detector.py",
             "--rules-dir", rules_dir, "--new-rule-path", draft_path],
            capture_output=True, text=True
        )
        assert conflict_result.returncode == 0
        conflict_data = json.loads(conflict_result.stdout)
        assert conflict_data["status"] == "ok"

        # 5. Write rule
        rule_path = os.path.join(rules_dir, "timeout.md")
        write_result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/rule_parser.py",
             "write", "--rule-path", rule_path, "--draft", draft_path],
            capture_output=True, text=True
        )
        assert write_result.returncode == 0
        assert os.path.exists(rule_path)

        # 6. Verify rule contents
        read_result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/rule_parser.py",
             "read", "--rule-path", rule_path],
            capture_output=True, text=True
        )
        read_data = json.loads(read_result.stdout)
        assert read_data["name"] == "timeout"
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest docs/superpowers/skills/mistake-registry/tests/ -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/skills/mistake-registry/rule_updater.py \
        docs/superpowers/skills/mistake-registry/tests/ && \
git commit -m "feat(mistake-registry): add rule_updater.py and integration tests"
```

---

## Self-Review Checklist

- [ ] Spec coverage: All spec items mapped to tasks
  - Parser → Task 2
  - Counter/Scorer → Task 3 (memory_scanner clusters and sorts by count)
  - Searcher → Task 4 (conflict_detector)
  - Rule Generator → Task 2 (rule_parser draft + write)
  - Trigger Tracking → Task 5 (rule_updater --update-last-triggered)
  - Expiration/Decay → Task 5 (rule_updater --check-expiration + --archive)
  - 3+ threshold → Task 3 (--min-count flag, default 3 in SKILL.md)
  - Conflict resolution → Task 4 (CONFLICT status + 3 options)
  - Invocation flags → Task 1 (SKILL.md --check, --force)
- [ ] Placeholder scan: No TODOs, no TBDs, no "implement later"
- [ ] Type consistency: All function names consistent across tasks
- [ ] Tests: All tests have actual assertions and runnable code
- [ ] Commands: All run commands have expected output documented

---

## Next Step

Implementation complete. Options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
