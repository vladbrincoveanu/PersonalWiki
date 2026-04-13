# YouTube Transcript API Integration Design

**Date:** 2026-04-13
**Status:** Approved

---

## Overview

Replace `yt-dlp` subtitle extraction with `youtube-transcript-api` — a purpose-built library that calls YouTube's transcript API directly (not the player API) and bypasses the HTTP 400 rate-limit that `yt-dlp` hits. Keep Whisper as the final fallback for videos with no captions.

---

## Problem

The current `yt-dlp`-based subtitle extraction fails with `HTTP 400: Precondition check failed` because YouTube's player API is rate-limiting all requests from this IP. The `youtube-transcript-api` library uses a different endpoint — YouTube's transcript download API — which is not subject to the same rate limiting.

---

## Solution: `youtube-transcript-api` as Primary

**Library:** `jdepoix/youtube-transcript-api`
**Installation:** `pip install youtube-transcript-api`
**Key advantage:** Uses `youtube.com/api/transcript` endpoint directly, not the player API.

### API Pattern

```python
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

ytt = YouTubeTranscriptApi()

# List available transcripts (useful for debugging)
transcripts = ytt.list(video_id)

# Find English transcript, prefer manually-created over auto-generated
transcript = (
    ytt.find_transcript(['en'])
    .find_manually_created_transcript()
    or ytt.find_transcript(['en']).find_generated_transcript()
)

# Fetch snippets
snippets = transcript.fetch()
text = " ".join(s["text"] for s in snippets)
```

### Tier Strategy (replacing yt-dlp tiers)

```
try_youtube_transcript_api():
  1. Find manually-created English transcript
  2. Find auto-generated English transcript (with is_generated detection)
  3. Try all available transcripts (any language, any type)
  4. If all fail → fall through to Whisper
```

---

## Fallback: Whisper Transcription

For videos with zero captions (e.g. music videos, no-caption talks):

1. Download audio via `yt-dlp -x --audio-format mp3 --skip-download` (fast, no transcoding)
2. Transcribe with Whisper (`openai/whisper`)
3. If Whisper fails → return `[NO_TRANSCRIPT] {url}` stub

**Whisper approach:** Use `openai-whisper` package with `base` model (fastest). No API call needed — runs locally. This is the ultimate fallback that works for ANY video.

---

## New `extract_youtube` Flow

```python
def extract_youtube(url: str) -> Document:
    video_id = _extract_video_id(url)  # already exists

    # Try youtube-transcript-api first (bypasses yt-dlp rate limit)
    transcript_text = _try_youtube_transcript_api(video_id)
    if transcript_text:
        return Document(raw_text=transcript_text, content_type="video")

    # Try yt-dlp subtitle tiers as 2nd attempt (may work if rate limit lifts)
    with tempfile.TemporaryDirectory() as tmpdir:
        transcript = _try_subtitle_tiers(url, tmpdir)
        if transcript and transcript.strip():
            return Document(raw_text=transcript, content_type="video")

    # Try yt-dlp audio + Whisper as last resort
    audio_text = _try_whisper_transcription(url)
    if audio_text:
        return Document(raw_text=audio_text, content_type="video")

    return Document(raw_text=f"[NO_TRANSCRIPT] {url}", content_type="video")
```

---

## Implementation: `_try_youtube_transcript_api`

```python
def _try_youtube_transcript_api(video_id: str) -> str | None:
    """Try to fetch English transcript via youtube-transcript-api.

    Strategy:
    1. Manually-created English
    2. Auto-generated English
    3. Any English transcript
    4. Any transcript (any language/type)

    Returns transcript text or None if all strategies fail.
    """
    try:
        ytt = YouTubeTranscriptApi()
        all_transcripts = ytt.list(video_id)

        # Priority: manually-created English > auto-generated English > any English > any
        en_transcripts = all_transcripts.find_transcript(["en"])

        transcript = (
            en_transcripts.find_manually_created_transcript()
            or en_transcripts.find_generated_transcript()
        )

        if not transcript:
            # Last resort: any transcript in any language
            if all_transcripts:
                transcript = all_transcripts[0]
            else:
                return None

        snippets = transcript.fetch()
        # Join all snippet texts preserving order
        text = " ".join(snippet["text"] for snippet in snippets)
        return text.strip() if text.strip() else None

    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        return None
    except Exception:
        # RequestBlocked, IpBlocked, etc. — fall through to yt-dlp
        return None
```

---

## Implementation: `_try_whisper_transcription`

```python
def _try_whisper_transcription(url: str) -> str | None:
    """Download audio via yt-dlp and transcribe with Whisper.

    Only called as last resort when no captions are available.
    Uses whisper 'base' model for speed (CPU, ~2x realtime on modern hardware).
    """
    try:
        import whisper
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "audio.mp3")

            # Download audio only (no video) — fastest approach
            cmd = [
                "yt-dlp",
                "-x", "--audio-format", "mp3",
                "--output", audio_path,
                "--quiet", "--no-warnings",
                url,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode != 0:
                return None

            # Transcribe with Whisper base model
            model = whisper.load_model("base")
            result = model.transcribe(audio_path, fp16=False)
            return result["text"].strip()

    except Exception:
        return None
```

**Note:** First call to `whisper.load_model("base")` downloads the model (~140MB). Subsequent calls use cached model.

---

## Testing

| Test | Description |
|------|-------------|
| `test_youtube_transcript_api_manually_created` | Mock finds manually-created English transcript |
| `test_youtube_transcript_api_auto_generated` | Mock no manual, finds auto-generated |
| `test_youtube_transcript_api_falls_through` | Mock returns None, falls through to yt-dlp |
| `test_whisper_transcription` | Mock yt-dlp audio download + Whisper transcription |
| `test_extract_youtube_full_pipeline` | Full flow: API → yt-dlp → Whisper → stub |

---

## Dependencies

- `pip install youtube-transcript-api` — no API key needed
- `pip install openai-whisper` — for audio transcription (local, no API)

---

## Out of Scope

- Caption translation (use YouTube's built-in transcript.translate() if needed)
- Speaker diarization
- Multi-language transcript merging
- Caching of Whisper results
