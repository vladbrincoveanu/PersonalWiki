#!/usr/bin/env python3
"""Apply smart keyword suppression to vault."""
from core.graph_interests import extract_interests
from core.keywords_manager import suppress_keyword, load_suppressed_keywords
from config import VAULT_PATH
from pathlib import Path

keywords_path = Path(VAULT_PATH) / "_keywords"

# Hard noise blocklist: ALWAYS suppress these
_HARD_NOISE = {
    # System prompt files
    "IDENTITY.md - Who Am I?",
    "HEARTBEAT.md",
    "USER.md - About Your Human",
    "SOUL.md - Who You Are",
    "AGENTS.md - Your Workspace",
    "TOOLS.md - Local Notes",
    # Error/failure states
    "error",
    "unavailable",
    "no-content",
    "no-transcript",
    "missing-content",
    # Overly generic
    "ai",
    "machine-learning",
    "deep-learning",
    "neural-networks",
    "educational",
    # Too generic alone (but keep compound forms)
    "techcrunch",
    "twitter",
    "youtube",
    "bitcoin",
    "bear-market",
    "recession",
    "business-cycle",
    "price-prediction",
    "tech-news",
    "3blue1brown",
    "llama",
    "karpathy",
    "rlhf",
    "meta",
    "openai",
}

candidates = extract_interests()
current_suppressed = set(load_suppressed_keywords(keywords_path))
to_suppress = _HARD_NOISE - current_suppressed

print(f"Candidates: {len(candidates)}")
print(f"Already suppressed: {len(current_suppressed)}")
print(f"Will suppress NEW: {len(to_suppress)}")
for kw in sorted(to_suppress):
    print(f"  SUPPRESS: {kw}")

if to_suppress:
    for kw in to_suppress:
        suppress_keyword(kw, keywords_path)
    print(f"\nSuppressed {len(to_suppress)} keywords.")
else:
    print("\nNothing new to suppress.")

# Show remaining candidates
print(f"\nRemaining keywords ({len(candidates)}):")
for kw in candidates:
    print(f"  {kw}")
