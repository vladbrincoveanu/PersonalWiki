# YouTube Transcript API Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `yt-dlp` subtitle extraction with `youtube-transcript-api` as primary extractor (bypasses HTTP 400 rate-limit), add `yt-dlp` subtitle tiers as 2nd attempt, add Whisper as final fallback for no-caption videos.

**Architecture:** `extract_youtube` calls: (1) `_try_youtube_transcript_api()` → (2) `_try_subtitle_tiers()` (existing yt-dlp loop) → (3) `_try_whisper_transcription()` → stub. Each returns `str | None`, pipeline short-circuits on first success.

**Tech Stack:** `youtube-transcript-api` (pip install), `openai-whisper` (pip install, local), existing `yt-dlp` + `subprocess`.

---

## Dependency Installation (Run once before tasks)

```bash
source .venv/bin/activate
pip install youtube-transcript-api openai-whisper
```

---

## File Map

| File | Change |
|------|--------|
| `ingesters/youtube.py` | Add `_try_youtube_transcript_api()`, add `_try_whisper_transcription()`, update `extract_youtube()` flow |
| `tests/test_youtube_ingester.py` | Add 4 new tests for API, auto-gen, fallback, and full pipeline |

---

## Task 1: Add `_try_youtube_transcript_api` + Tests

**Files:**
- Modify: `ingesters/youtube.py` — add `_try_youtube_transcript_api()`
- Test: `tests/test_youtube_ingester.py` — add tests

- [ ] **Step 1: Write failing tests**

```python
# tests/test_youtube_ingester.py — add these tests

def test_youtube_transcript_api_manually_created(monkeypatch):
    """youtube-transcript-api finds manually-created English transcript."""
    import ingesters.youtube as yt

    class FakeSnippet:
        def __init__(self, text):
            self.text = text

    class FakeTranscript:
        def __init__(self, snippets):
            self._snippets = snippets
        def fetch(self):
            return [{"text": s.text} for s in self._snippets]

    class FakeTranscriptList:
        def __init__(self, en_transcript):
            self._en = en_transcript
        def find_transcript(self, langs):
            return self
        def find_manually_created_transcript(self):
            return self._en
        def find_generated_transcript(self):
            return None

    fake_api_calls = []
    def mock_ytt(video_id):
        fake_api_calls.append(video_id)
        return FakeTranscriptList(FakeTranscript([FakeSnippet("Hello from transcript API")]))

    monkeypatch.setattr("ingesters.youtube.YouTubeTranscriptApi", mock_ytt)

    result = yt._try_youtube_transcript_api("abc123DEF12")
    assert result is not None
    assert "Hello from transcript API" in result
    assert fake_api_calls == ["abc123DEF12"]


def test_youtube_transcript_api_auto_generated(monkeypatch):
    """No manually-created, falls back to auto-generated."""
    import ingesters.youtube as yt

    class FakeSnippet:
        def __init__(self, text):
            self.text = text

    class FakeTranscript:
        def __init__(self, snippets):
            self._snippets = snippets
        def fetch(self):
            return [{"text": s.text} for s in self._snippets]

    class FakeTranscriptList:
        def __init__(self, en_transcript):
            self._en = en_transcript
        def find_transcript(self, langs):
            return self
        def find_manually_created_transcript(self):
            return None
        def find_generated_transcript(self):
            return self._en

    def mock_ytt(video_id):
        return FakeTranscriptList(FakeTranscript([FakeSnippet("Auto-generated transcript")]))

    monkeypatch.setattr("ingesters.youtube.YouTubeTranscriptApi", mock_ytt)

    result = yt._try_youtube_transcript_api("abc123DEF12")
    assert result is not None
    assert "Auto-generated transcript" in result


def test_youtube_transcript_api_falls_through(monkeypatch):
    """API raises NoTranscriptFound → returns None (falls through to yt-dlp)."""
    import ingesters.youtube as yt
    from youtube_transcript_api import NoTranscriptFound

    def mock_ytt(video_id):
        raise NoTranscriptFound("abc123", "en")

    monkeypatch.setattr("ingesters.youtube.YouTubeTranscriptApi", mock_ytt)

    result = yt._try_youtube_transcript_api("abc123DEF12")
    assert result is None
```

- [ ] **Step 2: Run tests — verify they fail (function doesn't exist)**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_youtube_ingester.py -k "transcript_api" -v
```

- [ ] **Step 3: Add `_try_youtube_transcript_api` to youtube.py**

Add after `_extract_video_id`, before `_try_subtitle_tiers`:

```python
def _try_youtube_transcript_api(video_id: str) -> str | None:
    """Try to fetch English transcript via youtube-transcript-api.

    Strategy:
    1. Manually-created English transcript
    2. Auto-generated English transcript
    3. Any transcript in any language (last resort)

    Returns transcript text or None if all strategies fail.
    """
    try:
        ytt = YouTubeTranscriptApi()
        all_transcripts = ytt.list(video_id)

        # Try for English first
        en_transcripts = all_transcripts.find_transcript(["en"])

        # Prefer manually-created over auto-generated
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
        text = " ".join(snippet["text"] for snippet in snippets)
        return text.strip() if text.strip() else None

    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        return None
    except Exception:
        # RequestBlocked, IpBlocked, etc. — fall through to yt-dlp
        return None
```

**Add import at top of file:**
```python
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)
```

- [ ] **Step 4: Run transcript_api tests — verify they pass**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_youtube_ingester.py -k "transcript_api" -v
```

- [ ] **Step 5: Commit**

```bash
git add ingesters/youtube.py tests/test_youtube_ingester.py
git commit -m "feat(youtube): add youtube-transcript-api as primary extractor"
```

---

## Task 2: Add `_try_whisper_transcription` + Tests

**Files:**
- Modify: `ingesters/youtube.py` — add `_try_whisper_transcription()`
- Test: `tests/test_youtube_ingester.py` — add test

- [ ] **Step 1: Write failing test**

```python
# tests/test_youtube_ingester.py — add this test

def test_whisper_transcription(monkeypatch, tmp_path):
    """yt-dlp downloads audio, Whisper transcribes it."""
    import ingesters.youtube as yt

    # Mock subprocess.run for yt-dlp audio download
    audio_file = tmp_path / "audio.mp3"
    audio_file.write_bytes(b"fake mp3 audio")

    subprocess_calls = []
    def mock_run(cmd, **kwargs):
        subprocess_calls.append(cmd)
        # Create the audio file where yt-dlp would
        audio_file.write_bytes(b"fake mp3 audio")
        return None

    # Mock whisper model and transcribe
    mock_model = MagicMock()
    mock_model.transcribe.return_value = {"text": "Whisper transcribed text from audio"}

    whisper_calls = []
    def mock_load_model(model_name):
        whisper_calls.append(model_name)
        return mock_model

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("ingesters.youtube.whisper.load_model", mock_load_model)

    result = yt._try_whisper_transcription("https://youtube.com/watch?v=abc123")
    assert result is not None
    assert "Whisper transcribed text" in result
    assert "abc123" in subprocess_calls[0][-1]  # URL in command
```

- [ ] **Step 2: Run test — verify it fails (function doesn't exist)**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_youtube_ingester.py -k "whisper" -v
```

- [ ] **Step 3: Add `_try_whisper_transcription` to youtube.py**

Add after `_try_youtube_transcript_api`:

```python
def _try_whisper_transcription(url: str) -> str | None:
    """Download audio via yt-dlp and transcribe with Whisper base model.

    Called as last resort when no captions are available.
    Uses whisper 'base' model for speed (CPU, ~2x realtime).
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
            transcription = model.transcribe(audio_path, fp16=False)
            text = transcription["text"].strip()
            return text if text else None

    except Exception:
        return None
```

**Note:** First call to `whisper.load_model("base")` downloads the model (~140MB). Subsequent calls use the cached model.

- [ ] **Step 4: Run Whisper test — verify it passes**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_youtube_ingester.py -k "whisper" -v
```

- [ ] **Step 5: Commit**

```bash
git add ingesters/youtube.py tests/test_youtube_ingester.py
git commit -m "feat(youtube): add Whisper transcription as final fallback"
```

---

## Task 3: Update `extract_youtube` Flow + Full Pipeline Test

**Files:**
- Modify: `ingesters/youtube.py` — update `extract_youtube()` call order
- Test: `tests/test_youtube_ingester.py` — add full pipeline test

- [ ] **Step 1: Write failing test**

```python
# tests/test_youtube_ingester.py — add this test

def test_extract_youtube_full_pipeline_all_fail(monkeypatch):
    """All sources fail → returns NO_TRANSCRIPT stub."""
    import ingesters.youtube as yt
    from youtube_transcript_api import NoTranscriptFound

    # youtube-transcript-api fails
    def mock_ytt_api(video_id):
        raise NoTranscriptFound(video_id, "en")

    # yt-dlp returns no subtitle files
    monkeypatch.setattr("ingesters.youtube._run_yt_dlp", lambda *a, **kw: None)

    # Whisper fails
    monkeypatch.setattr("ingesters.youtube.whisper.load_model", lambda m: (_ for _ in ()).throw(Exception("whisper fail")))

    monkeypatch.setattr("ingesters.youtube.YouTubeTranscriptApi", mock_ytt_api)

    doc = yt.extract_youtube("https://youtube.com/watch?v=abc123DEF12")
    assert doc.raw_text.startswith("[NO_TRANSCRIPT]")
    assert doc.content_type == "video"
```

- [ ] **Step 2: Run test — verify it fails (flow not updated)**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_youtube_ingester.py -k "full_pipeline" -v
```

- [ ] **Step 3: Update `extract_youtube`**

Replace the current `extract_youtube` function with:

```python
def extract_youtube(url: str) -> Document:
    video_id = _extract_video_id(url)

    # Try youtube-transcript-api first (bypasses yt-dlp rate limit)
    if video_id:
        api_transcript = _try_youtube_transcript_api(video_id)
        if api_transcript and api_transcript.strip():
            return Document(raw_text=api_transcript, content_type="video")

    # Try yt-dlp subtitle tiers as 2nd attempt
    with tempfile.TemporaryDirectory() as tmpdir:
        transcript = _try_subtitle_tiers(url, tmpdir)
        if transcript and transcript.strip():
            return Document(raw_text=transcript, content_type="video")

    # Try Whisper transcription as last resort
    whisper_transcript = _try_whisper_transcription(url)
    if whisper_transcript:
        return Document(raw_text=whisper_transcript, content_type="video")

    return Document(raw_text=f"[NO_TRANSCRIPT] {url}", content_type="video")
```

- [ ] **Step 4: Run full pipeline test — verify it passes**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_youtube_ingester.py -k "full_pipeline" -v
```

- [ ] **Step 5: Commit**

```bash
git add ingesters/youtube.py tests/test_youtube_ingester.py
git commit -m "feat(youtube): wire youtube-transcript-api -> yt-dlp -> Whisper pipeline"
```

---

## Task 4: Run Full Test Suite

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest -v --tb=short
```

- [ ] **Step 2: Verify all tests pass, fix any regressions**

---

## Spec Coverage Check

| Spec Requirement | Task |
|-----------------|------|
| youtube-transcript-api as primary (manually-created English) | Task 1 |
| Auto-generated English fallback | Task 1 |
| yt-dlp subtitle tiers as 2nd attempt | Task 3 (existing) |
| Whisper as final fallback | Task 2 |
| [NO_TRANSCRIPT] stub when all fail | Task 3 |
| All tests pass | Task 4 |
