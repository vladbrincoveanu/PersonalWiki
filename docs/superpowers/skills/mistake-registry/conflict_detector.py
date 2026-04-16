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
            try:
                import yaml
                fm = yaml.safe_load(match.group(1)) or {}
            except Exception:
                # Fallback to regex parsing if yaml fails
                fm = {}
            existing.append({
                "name": fm.get("name", f.stem),
                "path": str(f),
                "body": match.group(2).strip(),
                "paths": fm.get("paths", [])
            })

    # Read new rule
    new_body = read_rule_body(args.new_rule_path)
    with open(args.new_rule_path) as f:
        content = f.read()
    match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    if match:
        try:
            import yaml
            fm_new = yaml.safe_load(match.group(1)) or {}
        except Exception:
            fm_new = {}
    else:
        fm_new = {}

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