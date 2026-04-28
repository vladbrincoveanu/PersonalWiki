import os
import re
import subprocess
import tempfile
import whisper
from contextlib import contextmanager
from ingesters import Document
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)


def _get_proxy():
    """Return proxy dict/URL from config, or None if not set."""
    from config import YOUTUBE_PROXY
    if not YOUTUBE_PROXY:
        return None
    return YOUTUBE_PROXY


@contextmanager
def _proxy_env(proxy):
    """Temporarily set HTTP_PROXY/HTTPS_PROXY env vars, then restore."""
    if not proxy:
        yield
        return
    old_http = os.environ.get("HTTP_PROXY")
    old_https = os.environ.get("HTTPS_PROXY")
    os.environ["HTTP_PROXY"] = proxy
    os.environ["HTTPS_PROXY"] = proxy
    try:
        yield
    finally:
        if old_http is not None:
            os.environ["HTTP_PROXY"] = old_http
        else:
            os.environ.pop("HTTP_PROXY", None)
        if old_https is not None:
            os.environ["HTTPS_PROXY"] = old_https
        else:
            os.environ.pop("HTTPS_PROXY", None)

_TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->.*$", re.MULTILINE)
_TAG_RE = re.compile(r"<[^>]+>")
_CUE_SETTING_RE = re.compile(r"^(?:align|line|position|size|vertical):.*$", re.MULTILINE)

_whisper_model = None  # Module-level cache

def _get_whisper_model():
    """Load and cache Whisper model."""
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = whisper.load_model("base")
    return _whisper_model

_SUBTITLE_TIERS = [
    {"args": ["--write-subs", "--write-auto-subs", "--sub-langs", "en",      "--sub-format", "vtt", "--skip-download"], "name": "en"},
    {"args": ["--write-subs", "--write-auto-subs", "--sub-langs", "en.*",    "--sub-format", "vtt", "--skip-download"], "name": "en-regex"},
    {"args": ["--write-subs", "--write-auto-subs", "--all-subs",                                             "--skip-download"], "name": "all"},
    {"args": ["--write-auto-subs", "--write-subs", "--sub-langs", "en",      "--sub-format", "vtt", "--skip-download"], "name": "auto-en"},
]

_TIMEOUT_SECONDS = 30


def _parse_vtt(vtt_text: str) -> str:
    # Remove WEBVTT header block
    text = re.sub(r"^WEBVTT.*?\n\n", "", vtt_text, count=1, flags=re.DOTALL)
    # Remove timestamp cue lines
    text = _TIMESTAMP_RE.sub("", text)
    # Remove cue setting lines (align:, line:, etc.)
    text = _CUE_SETTING_RE.sub("", text)
    # Remove inline HTML tags
    text = _TAG_RE.sub("", text)
    # Split, strip, drop blanks, deduplicate consecutive identical lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    deduped: list[str] = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)
    return " ".join(deduped)


def _run_yt_dlp(url: str, args: list[str], tmpdir: str, proxy: str | None = None) -> list[str] | None:
    """Run yt-dlp with given args in tmpdir. Returns list of VTT file paths or None."""
    cmd = ["yt-dlp"] + args + ["--output", os.path.join(tmpdir, "%(id)s"), "--quiet", url]
    if proxy:
        cmd.insert(1, "--proxy")
        cmd.insert(2, proxy)
    try:
        subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT_SECONDS)
        vtt_files = [f for f in os.listdir(tmpdir) if f.endswith(".vtt")]
        if not vtt_files:
            return None
        return [os.path.join(tmpdir, f) for f in vtt_files]
    except Exception:
        return None


def _extract_video_id(url: str) -> str | None:
    """Extract video ID from YouTube URL."""
    m = re.search(r'(?:v=|/)([a-zA-Z0-9_-]{11})', url)
    return m.group(1) if m else None


def _try_youtube_transcript_api(video_id: str, proxy: str | None = None) -> str | None:
    """Try to fetch English transcript via youtube-transcript-api.

    Strategy:
    1. Manually-created English transcript
    2. Auto-generated English transcript
    3. Any transcript in any language (last resort)

    Returns transcript text or None if all strategies fail.
    """
    def _fetch():
        ytt = YouTubeTranscriptApi()
        all_transcripts = ytt.list(video_id)

        # Find best English transcript: manually-created > auto-generated
        english_transcripts = []
        for t in all_transcripts:
            if t.language_code.startswith("en"):
                english_transcripts.append(t)

        # Prefer manually-created over auto-generated
        transcript = None
        for t in english_transcripts:
            if not t.is_generated:
                transcript = t
                break
        if not transcript and english_transcripts:
            transcript = english_transcripts[0]

        if not transcript and all_transcripts:
            transcript = all_transcripts[0]

        if not transcript:
            return None

        snippets = transcript.fetch()
        text = " ".join(snippet.text for snippet in snippets)
        return text.strip() if text.strip() else None

    try:
        with _proxy_env(proxy):
            return _fetch()
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        return None
    except Exception:
        # RequestBlocked, IpBlocked, etc. — fall through to yt-dlp
        return None


def _try_whisper_transcription(url: str, proxy: str | None = None) -> str | None:
    """Download audio via yt-dlp and transcribe with Whisper base model.

    Called as last resort when no captions are available.
    Uses whisper 'base' model for speed (CPU, ~2x realtime).
    """
    try:
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
            if proxy:
                cmd.insert(1, "--proxy")
                cmd.insert(2, proxy)
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode != 0:
                return None

            # Transcribe with Whisper base model (cached at module level)
            model = _get_whisper_model()
            transcription = model.transcribe(audio_path, fp16=False)
            text = transcription["text"].strip()
            return text if text else None

    except Exception:
        return None


def _is_english_text(text: str, min_latin_ratio: float = 0.7) -> bool:
    """Return True if text appears to be English (Latin-script dominant)."""
    latin = sum(1 for c in text if c.isalpha() and ord(c) < 128)
    total = sum(1 for c in text if c.isalpha())
    if total == 0:
        return False
    return (latin / total) >= min_latin_ratio


def _has_english_cues(vtt_text: str) -> bool:
    """Check if VTT contains any English-language cues via lang= attr or char ratio."""
    for line in vtt_text.splitlines():
        # VTT cue format: "00:00:00.000 --> 00:00:05.000 align:start ... lang=en-US"
        if "lang=en" in line or "lang=en-" in line:
            return True
    # Fallback: character ratio check on text content lines
    text_lines = [l.strip() for l in vtt_text.splitlines()
                  if not l.startswith("00:") and "-->" not in l]
    sample = " ".join(text_lines[:50])
    return _is_english_text(sample)


def _get_video_metadata(url: str, proxy: str | None = None) -> dict | None:
    """Get video title and description via yt-dlp --dump-json."""
    cmd = ["yt-dlp", "--dump-json", "--quiet", "--no-download", url]
    if proxy:
        cmd.insert(1, "--proxy")
        cmd.insert(2, proxy)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        if result.returncode != 0:
            return None
        import json
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
        return {
            "title": data.get("title", ""),
            "description": data.get("description", ""),
        }
    except Exception:
        return None


def _try_subtitle_tiers(url: str, tmpdir: str, proxy: str | None = None) -> str | None:
    """Try each subtitle tier. Returns transcript text or None."""
    for tier in _SUBTITLE_TIERS:
        vtt_files = _run_yt_dlp(url, tier["args"], tmpdir, proxy)
        if vtt_files:
            for vtt_file in vtt_files:
                with open(vtt_file, encoding="utf-8") as f:
                    vtt_text = f.read()
                # For auto-en tier, filter for English; for other tiers accept all
                if tier["name"] == "auto-en" and not _has_english_cues(vtt_text):
                    continue  # try next VTT file or next tier
                transcript = _parse_vtt(vtt_text)
                if transcript.strip():
                    return transcript
    return None


def extract_youtube(url: str) -> Document:
    video_id = _extract_video_id(url)
    proxy = _get_proxy()

    # Try youtube-transcript-api first (bypasses yt-dlp rate limit)
    if video_id:
        api_transcript = _try_youtube_transcript_api(video_id, proxy)
        if api_transcript and api_transcript.strip():
            return Document(raw_text=api_transcript, content_type="video")

    # Try yt-dlp subtitle tiers as 2nd attempt
    with tempfile.TemporaryDirectory() as tmpdir:
        transcript = _try_subtitle_tiers(url, tmpdir, proxy)
        if transcript and transcript.strip():
            return Document(raw_text=transcript, content_type="video")

    # Try Whisper transcription as last resort (only if we had a valid video_id)
    if video_id:
        whisper_transcript = _try_whisper_transcription(url, proxy)
        if whisper_transcript:
            return Document(raw_text=whisper_transcript, content_type="video")

    # Final fallback: use video title + description as raw text
    meta = _get_video_metadata(url, proxy)
    if meta and (meta.get("title") or meta.get("description")):
        parts = []
        if meta.get("title"):
            parts.append(f"Title: {meta['title']}")
        if meta.get("description"):
            desc = meta["description"][:2000]
            parts.append(f"Description: {desc}")
        if parts:
            return Document(raw_text="\n\n".join(parts), content_type="video")

    return Document(raw_text=f"[NO_TRANSCRIPT] {url}", content_type="video")


def score_video_priority(video: dict, user_keywords: list[str]) -> dict:
    """
    Score a video by topic match, recency, and engagement.
    Returns the video dict with an added "priority_score" key.

    Weights: topic_match=0.6, recency=0.25, engagement=0.15
    """
    topic_score = video.get("topic_match", 0.0)
    days_old = video.get("days_old", 999)
    recency_score = max(0.0, 1.0 - (days_old / 365))
    views = video.get("views", 0)
    engagement_score = min(1.0, (views ** 0.5) / 10000)

    priority_score = (
        0.60 * topic_score +
        0.25 * recency_score +
        0.15 * engagement_score
    )

    video["priority_score"] = priority_score
    return video
