# Pre-Write Content Quality Gate

## Problem

After enrichment, `run_pipeline` writes notes without checking if the enriched content is meaningful. The existing `QualityGate.check()` only gates on raw extraction quality. Junk content that passes extraction but produces low-quality enriched output still gets written to the vault. The `cleanup_junk()` reactive cleaner only catches narrow patterns (`[NO_TRANSCRIPT]`, `[TRANSLATION_FAILED]`, video < 50 chars) and cannot prevent junk from accumulating.

## Solution

Add a **pre-write gate** inside `run_pipeline` after enrichment (Step 3) and before write (Step 4). It checks enriched content quality — rejecting thin or noise-heavy content — before `write_note()` is called.

## Architecture

### Pipeline flow (pipeline.py)

```
Step 3: Enrich → note{} + raw_text
        ↓
Pre-write gate: _gate_enriched_content(note, raw_text)
        ↓ (pass) → Step 4: write_note + index
        ↓ (fail) → yield skip message, return (no write, no index)
```

### Module: `core/prose.py` (new file)

Extract `_measure_prose()` from `discovery_scheduler.py` so both modules can use it.

**Responsibility:** Measure prose quality of text — extract alphabetic-heavy paragraph blocks and compute prose char count and ratio.

**Interface:**
```
measure_prose(text: str) -> tuple[int, float]  # (prose_chars, prose_ratio)
```

**Dependencies:** None (pure text processing).

**Size target:** ~30 lines.

### Module: `pipeline.py` (changes only)

Add `_gate_enriched_content(note: dict, raw_text: str) -> tuple[bool, int, float]`:
- Computes prose on `note.get("summary", "") + note.get("key_facts", "")`
- Returns `(pass: bool, prose_chars: int, prose_ratio: float)` — pass is `True` if content is acceptable

## Gate Checks

For **all content types**:
- **Hard minimum**: total prose chars ≥ 300
- **Prose ratio**: prose_chars / raw_text_chars ≥ 0.20 (20%)

For **video only** (additional check):
- If raw_text has < 5 actual word-tokens after stripping timestamps/numbers, reject even if prose checks pass (video transcripts that are mostly timestamps have no readable content)

## Gate Implementation

```python
def _gate_enriched_content(note: dict, raw_text: str) -> tuple[bool, int, float]:
    """Return (pass, prose_chars, prose_ratio) for enriched content quality check."""
    summary = note.get("summary", "") or ""
    key_facts = " ".join(note.get("key_facts", []))
    enriched_text = summary + " " + key_facts

    prose_chars, prose_ratio = measure_prose(enriched_text)
    total_chars = len(raw_text.strip())

    # Hard minimum: need meaningful prose
    if prose_chars < 300:
        return False, prose_chars, prose_ratio

    # Prose ratio: content must not be mostly noise
    if total_chars > 0 and prose_ratio < 0.20:
        return False, prose_chars, prose_ratio

    # Video-specific: raw_text must have actual words (not just timestamps)
    if note.get("content_type") == "video":
        words = [w for w in raw_text.split() if any(c.isalpha() for c in w)]
        if len(words) < 5:
            return False, prose_chars, prose_ratio

    return True, prose_chars, prose_ratio
```

## Error Handling

### Skip message format

When pre-write gate rejects content, yield (using the returned prose_chars and prose_ratio):
```
f"Skipped: Content too thin (prose={prose_chars}, ratio={prose_ratio:.0%}, need ≥300 chars, ≥20%)"
```

### Discovery cycle integration

When `run_pipeline` skips via pre-write gate, the discovery scheduler's `_update_keyword_score(keyword, -2)` already fires via the exception path in `_run_discovery_cycle`. No changes needed to `discovery_scheduler.py`.

### What gets indexed on skip

Nothing — both `write_note()` and `store.upsert()` are skipped. URL stays in `_seen_urls` so it won't be re-ingested in the same cycle.

## What This Does Not Change

- `QualityGate.check()` at Step 1.5 stays — it gates raw extraction quality before enrichment
- `cleanup_junk()` stays — reactive cleanup for edge cases that slip through
- Discovery scheduler URL pre-screening stays — this is a content-quality gate, not a URL-quality gate
- Ingester extractors stay unchanged — they continue to handle their own paywall/thin fallbacks

## Testing

- `test_pipeline_pre_write_gate_rejects_thin_enriched_content()` — mock enrich to return tiny summary, verify skip
- `test_pipeline_pre_write_gate_rejects_low_prose_ratio()` — mock enrich with noise-heavy content, verify skip
- `test_pipeline_pre_write_gate_accepts_valid_content()` — ensure real content passes through
- `test_video_pre_write_gate_rejects_timestamp_heavy_transcript()` — video with mostly timestamps rejected

## Files Changed

1. `core/prose.py` — new file, extracted from `discovery_scheduler.py`
2. `pipeline.py` — add `_gate_enriched_content()` and call it between Step 3 and Step 4
