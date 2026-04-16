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
from datetime import datetime, timedelta, date

ARCHIVE_DIR = ".archived"
EXPIRATION_DAYS = 60

def update_last_triggered(rules_dir: Path, rule_name: str) -> dict:
    for f in rules_dir.rglob("*.md"):
        if ".archived" in f.parts:
            continue
        with open(f) as fh:
            content = fh.read()
        match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
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
        last_triggered_raw = fm.get("last_triggered", "null")
        # YAML parses YYYY-MM-DD as datetime.date; convert to ISO string for comparison
        if isinstance(last_triggered_raw, date):
            last_triggered = last_triggered_raw.isoformat()
        else:
            last_triggered = last_triggered_raw
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