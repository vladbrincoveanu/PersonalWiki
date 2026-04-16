#!/usr/bin/env python3
"""
memory_scanner.py — Parse MEMORY.md, extract error entries, cluster by pattern.

Usage:
    python3 memory_scanner.py --memory-path <path> [--min-count <N>]
"""

import json
import argparse
import yaml
from collections import defaultdict

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
            # Ensure timestamp is string (yaml may parse YYYY-MM-DD as date)
            ts = fm.get("timestamp", "")
            if hasattr(ts, 'isoformat'):
                ts = ts.isoformat()
            entries.append({
                "name": fm.get("name", ""),
                "error": fm.get("error", ""),
                "file": fm.get("file", ""),
                "timestamp": ts,
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