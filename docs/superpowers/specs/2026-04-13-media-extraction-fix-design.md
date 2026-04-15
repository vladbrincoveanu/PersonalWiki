# Media Extraction Fix Design

**Date:** 2026-04-13
**Status:** Approved

---

## Overview

Fix two broken media type ingesters: YouTube video transcripts and Tweet extraction via Nitter. Both fail silently or return empty content.

---

## Issue 1 — YouTube Transcript Extraction

**Problem:** `yt-dlp --write-subs --sub-langs en` produces no VTT files for many videos. 59 chars extracted indicates the video metadata was fetched but no subtitle track was found.

**Root cause:** `--sub-langs en` requires exact match. Many videos have `en-US`, `en-GB`, or captions in other languages.

### Tiered Fallback Strategy

`extract_youtube(url: str) -> Document`

```python
TIERS = [
    {"args": ["--sub-langs", "en"],                    "timeout": 30, "name": "en exact"},
    {"args": ["--sub-langs", "en.*", "--sub-format", "vtt"], "timeout": 30, "name": "en regex"},
    {"args": ["--all-subs"],                             "timeout": 30, "name": "all subs"},
]
```

For each tier:
1. Clean tmpdir before each attempt
2. Run `yt-dlp` with tier args
3. Check for non-empty VTT files
4. If found: parse and return transcript
5. If not found: try next tier
6. If all tiers fail: try YouTube transcript API as final fallback
7. If all fail: return `Document(raw_text=f"[NO_TRANSCRIPT] {url}", content_type="video")`

### YouTube Transcript API Fallback

```python
def _fetch_youtube_transcript_api(video_id: str) -> str | None:
    """Try youtubetranscript.com API as final fallback."""
    import urllib.request
    url = f"https://youtubetranscript.com/?v={video_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            if "<transcript>" in content:
                # Parse XML manually
                text = re.sub(r"<[^>]+>", "", content)
                return text.strip()
    except Exception:
        return None
    return None
```

Extract `video_id` from URL using existing regex or `yt-dlp --get-id` output.

### Timeout and Cleanup

- Each `yt-dlp` invocation: 30 second timeout
- Transcript API fallback: 10 second timeout
- `finally` block ensures temp directory cleanup between tier attempts

---

## Issue 2 — Tweet Extraction via Nitter

**Problem:** All 4 hardcoded Nitter instances return no content. CSS selectors in `_CONTENT_RE` may be stale.

**Root cause:** Nitter frontends change their HTML structure frequently. The `class="tweet-content"` selector is likely broken.

### Expanded Instance Pool

```python
_NITTER_INSTANCES = [
    # Primary pool
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.unixfox.eu",
    "https://nitter.net",
    # Expanded pool
    "https://nitter.esmailelBob.xyz",
    "https://nitter.woodwhyn.vercel.app",
    "https://nitter.bus-hit.me",
    "https://nitter.projectsegfau.lt",
    # Syndication RSS fallback (always works if URL is public)
    None,  # placeholder — use syndication API below
]
```

### CSS Selector Update

After inspecting current Nitter HTML, update `_CONTENT_RE` to match actual DOM structure. Expected selectors to try:
- `class="tweet-content"` (old, likely broken)
- `class="p-text"` (current Nitter)
- `div[lang]` (Twitter native lang attribute)
- Plain text extraction: `<div class="reply">` (fallback)

New approach: use `re.DOTALL` to extract all text between tweet div boundaries, then strip tags, rather than relying on fragile class names.

### Syndication RSS Fallback

```python
def _fetch_via_syndication(username: str, tweet_id: str) -> str | None:
    """Use Twitter's public RSS endpoint as last resort."""
    import urllib.request
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            # Parse for tweet text matching tweet_id
            ...
    except Exception:
        return None
```

### Graceful Degradation

Instead of raising `ValueError` when all sources fail, return a stub:
```python
return Document(raw_text=f"[NO_TWEET] {url}", content_type="tweet")
```
This prevents the pipeline from crashing — the stub note gets written and indexed.

---

## File Changes

| File | Change |
|------|--------|
| `ingesters/youtube.py` | Add tiered subtitle fallback, transcript API fallback, better timeout handling |
| `ingesters/tweet.py` | Expand instance pool, update CSS selectors, add syndication fallback, graceful stub instead of raise |

---

## Dependencies

- No new dependencies — all HTTP libs are stdlib

---

## Testing

| Test | Description |
|------|-------------|
| `test_youtube_tiered_subtitle_fallback` | Mock yt-dlp to return empty on en,字幕 on en.* |
| `test_youtube_transcript_api_fallback` | Mock transcript API success and failure paths |
| `test_youtube_no_transcript_returns_stub` | All tiers fail → stub document |
| `test_tweet_expanded_instances` | Mock 4 new instances failing, 5th succeeding |
| `test_tweet_syndication_fallback` | Mock syndication returning tweet content |
| `test_tweet_all_fail_returns_stub` | All sources fail → stub document, no exception |

---

## Out of Scope

- YouTube video download (audio/video) — only transcripts
- Twitter API authentication — all approaches remain API-key-free
