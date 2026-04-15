# Skip Low-Quality Extractions — Design

## Problem

The pipeline saves notes even when extraction yields no real content (paywalled pages, 404 errors, blocked content). These notes are noise in the vault and waste storage.

## Rule

**Only save when extraction returns real content.** Failed/bad extractions are logged, never written to disk.

## Gate: `pipeline.py`

After Step 1 (Extract), before Step 4 (Write):

```python
# Check content quality — skip bad extractions
raw_text = doc.raw_text
stripped = raw_text.strip()
_error_signals = ["[PAYWALLED]", "[PAYWALL]", "404", "Page not found", "[BOTECTED]"]
is_error_signal = any(signal in stripped for signal in _error_signals)

if not stripped or len(stripped) < 100 or is_error_signal:
    yield f"Skipped: no extractable content ({len(stripped)} chars)"
    return
```

This catches:
- Empty or near-empty responses
- Paywall placeholder text
- 404 / page-not-found pages
- Known bot-block signals

## Changes

| File | Change |
|------|--------|
| `pipeline.py` | Add content quality gate after extraction; yield "Skipped" instead of saving |
| `write_note` | Remove `confidence: low` handling — no longer needed since bad content is never written |

## Test Cases

| Input | Result |
|-------|--------|
| Paywalled page (returns `[PAYWALLED]`) | Yields "Skipped", no file |
| 404 page (returns `404\nPage not found`) | Yields "Skipped", no file |
| Real article | Saved as before |

## Logging

All skipped extractions are already yielded as messages. The caller (API stream) receives them and can log as needed. No additional logging infrastructure needed.
