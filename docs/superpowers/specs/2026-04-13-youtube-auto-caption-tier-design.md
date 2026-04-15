# YouTube Auto-Caption Tier Design

**Date:** 2026-04-13
**Status:** Approved

---

## Overview

Add a 4th subtitle extraction tier for YouTube that specifically targets auto-generated English captions via `yt-dlp --write-auto-subs`, then filters the output for English-language text. This fills the gap between the current 3-tier loop and the API fallback.

---

## Problem

The current 3-tier approach (`en` exact → `en.*` regex → `all-subs`) fails for many videos that have auto-generated captions. YouTube automatically generates English captions for most videos, but these are:
1. Not included in `--sub-langs en` (they're treated as a separate track type)
2. Not matched by `--sub-langs en.*` (they use `en-US` style tags but aren't in the language pack)
3. Included in `--all-subs` but mixed with all other languages

Auto-generated captions are the single largest untapped source for YouTube transcripts.

---

## Solution: Tier 4 — Auto-Caption English Filter

**Approach:** Add a 4th tier between `all-subs` and the API fallback. This tier:
1. Runs `yt-dlp` with `--write-auto-subs --write-subs --sub-langs en --skip-download`
2. Parses the resulting VTT and detects English text via character distribution
3. If >30% of the text is Latin-script and plausible English, returns the transcript

**Why character distribution:** Auto-generated captions sometimes garble words. We use a heuristic: if the caption contains recognizable English words (via a short allowlist of common English trigrams), it's likely English. Simpler: count Latin characters vs total characters — English text should be >70% Latin characters.

**Better approach: VTT lang detection.** VTT captions can specify `lang=` in the cue payload. Check for `lang=en` or `lang=en-US` in the cue settings line. Auto-generated captions often have this.

---

## Implementation

### Tier 4 Definition

```python
_AUTO_CAPTION_TIER = {
    "args": ["--write-auto-subs", "--write-subs", "--sub-langs", "en", "--sub-format", "vtt", "--skip-download"],
    "name": "auto-en",
}
```

### English Detection

```python
def _is_english_text(text: str, min_latin_ratio: float = 0.7) -> bool:
    """Return True if text appears to be English (Latin-script dominant)."""
    latin = sum(1 for c in text if c.isalpha() and ord(c) < 128)
    total = sum(1 for c in text if c.isalpha())
    if total == 0:
        return False
    return (latin / total) >= min_latin_ratio


def _has_english_cues(vtt_text: str) -> bool:
    """Check if VTT contains any English-language cues."""
    for line in vtt_text.splitlines():
        # VTT cue format: "00:00:00.000 --> 00:00:05.000 align:start position:50% line:84% size:100% font-family:\"YouTube Sans\" lang=en-US"
        if "lang=en" in line or "lang=en-" in line:
            return True
    # Fallback: character ratio check on full text
    text_lines = [l.strip() for l in vtt_text.splitlines() if not l.startswith("00:") and "-->" not in l]
    sample = " ".join(text_lines[:50])
    return _is_english_text(sample)
```

### `_try_subtitle_tiers` Updated Loop

The tier loop becomes:

```python
_SUBTITLE_TIERS = [
    {"args": ["--write-subs", "--write-auto-subs", "--sub-langs", "en",      "--sub-format", "vtt", "--skip-download"], "name": "en"},
    {"args": ["--write-subs", "--write-auto-subs", "--sub-langs", "en.*",    "--sub-format", "vtt", "--skip-download"], "name": "en-regex"},
    {"args": ["--write-subs", "--write-auto-subs", "--all-subs",                                             "--skip-download"], "name": "all"},
    {"args": ["--write-auto-subs", "--write-subs", "--sub-langs", "en",      "--sub-format", "vtt", "--skip-download"], "name": "auto-en"},
]
```

Tier 4 (`auto-en`) is tried 4th, after `all-subs` but before API. When a tier produces VTT files, we check English detection before accepting. If the VTT is not English, continue to next tier.

---

## Tier Retry Logic

```python
def _try_subtitle_tiers(url: str, tmpdir: str) -> str | None:
    for tier in _SUBTITLE_TIERS:
        vtt_files = _run_yt_dlp(tier["args"], tmpdir)
        if vtt_files:
            for vtt_file in vtt_files:
                with open(vtt_file, encoding="utf-8") as f:
                    vtt_text = f.read()
                # For auto-en tier, filter for English
                if tier["name"] == "auto-en" and not _has_english_cues(vtt_text):
                    continue  # try next VTT or next tier
                transcript = _parse_vtt(vtt_text)
                if transcript.strip():
                    return transcript
    return None
```

---

## Testing

| Test | Description |
|------|-------------|
| `test_auto_caption_tier_finds_english_auto_subs` | Auto-captions with `lang=en-US` are detected and extracted |
| `test_auto_caption_tier_skips_non_english` | Auto-captions that are non-English are skipped, falling through to API |
| `test_auto_caption_tier_with_english_ratio_fallback` | When no lang= attribute, character ratio check is used |

---

## Out of Scope

- Downloading video/audio
- Caption translation
- Speaker diarization
- Timestamp alignment fixes
