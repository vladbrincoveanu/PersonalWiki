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
from datetime import date, datetime

def _json_safe(val):
    """Convert date/datetime objects to ISO strings for JSON serialization."""
    if isinstance(val, (date, datetime)):
        return val.isoformat()
    return val

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
description: "TODO: write one-line description"
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
        "last_triggered": _json_safe(fm.get("last_triggered")),
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
            "last_triggered": _json_safe(fm.get("last_triggered")),
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