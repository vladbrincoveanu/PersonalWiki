# core/prose.py
"""Prose quality measurement utilities."""
import re

def measure_prose(text: str) -> tuple[int, float]:
    """Return (prose_char_count, prose_ratio) for text.

    Prose blocks: split by double newlines, filter blocks with <3 words,
    all-caps blocks, and blocks with <30% alphabetic chars.
    """
    total_chars = len(text.strip())
    if total_chars == 0:
        return 0, 0.0

    blocks = re.split(r"\n\s*\n", text.strip())
    prose_chars = 0

    for block in blocks:
        block = block.strip()
        words = block.split()
        if len(words) < 3:
            continue
        # Skip all-caps blocks (headings, nav)
        if block.isupper():
            continue
        # Skip blocks with mostly symbols (tables, data)
        alpha = sum(1 for c in block if c.isalpha())
        if alpha / len(block) < 0.3:
            continue
        prose_chars += len(block)

    ratio = prose_chars / total_chars if total_chars > 0 else 0.0
    return prose_chars, ratio
