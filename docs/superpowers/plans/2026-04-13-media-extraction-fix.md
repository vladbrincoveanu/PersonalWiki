# Media Extraction Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix YouTube transcript extraction (tiered fallback + transcript API) and Tweet extraction (expanded Nitter pool + CSS selectors + syndication RSS + graceful stub).

**Architecture:** Two independent ingester fixes. YouTube adds a tier loop over yt-dlp subtitle options then falls back to a transcript API. Tweet ingester expands instance pool, fixes CSS selectors, adds syndication fallback, and returns a stub Document instead of raising.

**Tech Stack:** stdlib `urllib`, `subprocess` for yt-dlp, no new dependencies.

---

## File Map

| File | Change |
|------|--------|
| `ingesters/youtube.py` | Add `_TIERS`, `_fetch_transcript_api()`, update `extract_youtube()` with tier loop |
| `ingesters/tweet.py` | Add `_NITTER_INSTANCES`, `_fetch_via_syndication()`, fix selectors, return stub instead of raise |
| `tests/test_youtube_ingester.py` | Add tier fallback, transcript API, stub tests |
| `tests/test_tweet_ingester.py` | Add expanded instances, syndication, stub tests |

---

## Task 1: Fix YouTube — Tiered Subtitle Fallback

**Files:**
- Modify: `ingesters/youtube.py` — replace `extract_youtube()` body with tier loop
- Test: `tests/test_youtube_ingester.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_youtube_ingester.py — add these tests

def test_extract_youtube_tiered_subtitle_fallback(monkeypatch, tmp_path):
    """Tier 1 (en) fails, tier 2 (en.*) returns transcript."""
    calls = []
    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        # Tier 1 (en) — return empty
        if "--sub-langs" in cmd and "en" in cmd and ".*" not in str(cmd):
            return None  # no vtt files
        # Tier 2 (en.*) — return a vtt file
        vtt_file = tmp_path / "video.en.vtt"
        vtt_file.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:05.000\nHello world transcript")
        return str(vtt_file)

    import ingesters.youtube as yt
    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("os.listdir", lambda d: ["video.en.vtt"] if "tmp" in d else [])

    # Simulate the tier loop behavior
    from pathlib import Path
    import tempfile
    # Test the tier logic directly
    result = yt._try_subtitle_tiers("https://youtube.com/watch?v=abc", tmp_path)
    assert result is not None  # tier 2 succeeded


def test_extract_youtube_all_tiers_fail_then_transcript_api(monkeypatch, tmp_path):
    """All yt-dlp tiers fail, transcript API returns transcript."""
    import ingesters.youtube as yt

    tier_calls = []
    def mock_yt_dlp(*args, **kwargs):
        tier_calls.append(args)
        return None  # no vtt files produced

    api_calls = []
    def mock_transcript_api(video_id):
        api_calls.append(video_id)
        return "API transcript text here"

    monkeypatch.setattr("ingesters.youtube._run_yt_dlp", mock_yt_dlp)
    monkeypatch.setattr("ingesters.youtube._fetch_transcript_api", mock_transcript_api)

    doc = yt.extract_youtube("https://youtube.com/watch?v=abc123")
    assert "API transcript text" in doc.raw_text


def test_extract_youtube_returns_stub_when_all_fail(monkeypatch):
    """All tiers and API fail → return NO_TRANSCRIPT stub."""
    import ingesters.youtube as yt

    monkeypatch.setattr("ingesters.youtube._run_yt_dlp", lambda *a, **kw: None)
    monkeypatch.setattr("ingesters.youtube._fetch_transcript_api", lambda vid: None)

    doc = yt.extract_youtube("https://youtube.com/watch?v=abc")
    assert doc.raw_text.startswith("[NO_TRANSCRIPT]")
    assert doc.content_type == "video"
```

- [ ] **Step 2: Run tests — verify they fail (functions don't exist yet)**

```bash
pytest tests/test_youtube_ingester.py -v
```

- [ ] **Step 3: Implement tiered fallback in youtube.py**

```python
# ingesters/youtube.py — rewrite extract_youtube()

_SUBTITLE_TIERS = [
    {"args": ["--write-subs", "--write-auto-subs", "--sub-langs", "en",      "--sub-format", "vtt", "--skip-download"], "name": "en"},
    {"args": ["--write-subs", "--write-auto-subs", "--sub-langs", "en.*",    "--sub-format", "vtt", "--skip-download"], "name": "en-regex"},
    {"args": ["--write-subs", "--write-auto-subs", "--all-subs",                                             "--skip-download"], "name": "all"},
]

_TIMEOUT_SECONDS = 30


def _run_yt_dlp(args: list[str], tmpdir: str) -> list[str] | None:
    """Run yt-dlp with given args in tmpdir. Returns list of VTT file paths or None."""
    cmd = ["yt-dlp"] + args + ["--output", os.path.join(tmpdir, "%(id)s"), "--quiet"]
    try:
        subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT_SECONDS)
        vtt_files = [f for f in os.listdir(tmpdir) if f.endswith(".vtt")]
        if not vtt_files:
            return None
        return [os.path.join(tmpdir, f) for f in vtt_files]
    except Exception:
        return None


def _fetch_transcript_api(video_id: str) -> str | None:
    """Fallback via youtubetranscript.com API. Returns transcript text or None."""
    import urllib.request
    url = f"https://youtubetranscript.com/?v={video_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            if "<transcript>" not in content:
                return None
            # Strip XML tags to get plain text
            import re
            text = re.sub(r"<[^>]+>", "", content)
            return text.strip()
    except Exception:
        return None


def _extract_video_id(url: str) -> str | None:
    """Extract video ID from YouTube URL."""
    m = re.search(r'(?:v=|/)([a-zA-Z0-9_-]{11})', url)
    return m.group(1) if m else None


def extract_youtube(url: str) -> Document:
    import tempfile
    video_id = _extract_video_id(url)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Try each subtitle tier
        for tier in _SUBTITLE_TIERS:
            vtt_files = _run_yt_dlp(tier["args"], tmpdir)
            if vtt_files:
                # Found subtitles — parse and return
                with open(vtt_files[0], encoding="utf-8") as f:
                    vtt_text = f.read()
                transcript = _parse_vtt(vtt_text)
                if transcript.strip():
                    return Document(raw_text=transcript, content_type="video")

        # All yt-dlp tiers failed — try transcript API
        if video_id:
            transcript = _fetch_transcript_api(video_id)
            if transcript and transcript.strip():
                return Document(raw_text=transcript, content_type="video")

        # All fallbacks exhausted
        return Document(raw_text=f"[NO_TRANSCRIPT] {url}", content_type="video")
```

- [ ] **Step 4: Run YouTube tests — verify they pass**

```bash
pytest tests/test_youtube_ingester.py -v
```

- [ ] **Step 5: Commit**

```bash
git add ingesters/youtube.py tests/test_youtube_ingester.py
git commit -m "feat(youtube): tiered subtitle fallback + transcript API fallback"
```

---

## Task 2: Fix Tweet — Expanded Pool + CSS Fix + Syndication + Graceful Stub

**Files:**
- Modify: `ingesters/tweet.py` — update instance pool, fix selectors, add syndication, return stub
- Test: `tests/test_tweet_ingester.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tweet_ingester.py — add these tests

def test_tweet_expanded_instance_pool(monkeypatch):
    """First 4 instances fail, 5th (nitter.esmailelBob.xyz) returns content."""
    import ingesters.tweet as tw

    called = []
    def mock_urlopen(url, timeout=10):
        called.append(str(url))
        # First 4 fail
        if len(called) < 5:
            raise Exception("connection failed")
        # 5th succeeds — return HTML with tweet content
        html = b'<div class="p-text">Hello from tweet</div><span class="username">@user</span>'
        from unittest.mock import MagicMock
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, *a: None
        m.read.return_value = html
        m.status = 200
        return m

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    doc = tw.extract_tweet("https://twitter.com/user/status/123")
    assert "Hello from tweet" in doc.raw_text
    assert doc.content_type == "tweet"


def test_tweet_syndication_fallback(monkeypatch):
    """All Nitter instances fail, syndication returns content."""
    import ingesters.tweet as tw

    nitter_calls = []
    syndication_calls = []
    def mock_urlopen(url, timeout=10):
        url_str = str(url)
        if "syndication.twitter" in url_str:
            syndication_calls.append(url_str)
            html = b'<p class="timeline-message">Syndication tweet text</p>'
            from unittest.mock import MagicMock
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.read.return_value = html
            m.status = 200
            return m
        nitter_calls.append(url_str)
        raise Exception("Nitter down")

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    doc = tw.extract_tweet("https://twitter.com/user/status/123")
    assert "Syndication tweet text" in doc.raw_text
    assert doc.content_type == "tweet"


def test_tweet_all_sources_fail_returns_stub(monkeypatch):
    """All Nitter + syndication fail → return NO_TWEET stub, don't raise."""
    import ingesters.tweet as tw

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: (_ for _ in ()).throw(Exception("all down")))

    doc = tw.extract_tweet("https://twitter.com/user/status/123")
    assert doc.raw_text.startswith("[NO_TWEET]")
    assert doc.content_type == "tweet"
    assert "[NO_TWEET]" in doc.raw_text


def test_tweet_strips_html_correctly():
    """HTML-stripped tweet text contains actual content, not tags."""
    import ingesters.tweet as tw
    # Test the _strip_tags helper
    html = '<div class="p-text">Hello <b>world</b></div>'
    result = tw._strip_tags(html)
    assert "Hello world" in result
    assert "<" not in result
```

- [ ] **Step 2: Run tests — verify they fail (methods don't exist yet)**

```bash
pytest tests/test_tweet_ingester.py -v
```

- [ ] **Step 3: Implement tweet fixes**

```python
# ingesters/tweet.py — full rewrite of instance pool, extract_tweet, helpers

import re
import urllib.request
from ingesters import Document

# Expanded instance pool (primary + expanded + syndication handled in code)
_NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.unixfox.eu",
    "https://nitter.net",
    "https://nitter.esmailelBob.xyz",
    "https://nitter.woodwhyn.vercel.app",
    "https://nitter.bus-hit.me",
    "https://nitter.projectsegfau.lt",
]

# Updated CSS/content regex — more permissive extraction
_TAG_RE = re.compile(r"<[^>]+>")
_HANDLE_RE = re.compile(r'class="username"[^>]*>@?([^<\s]+)')
_NAME_RE = re.compile(r'class="fullname"[^>]*>([^<]+)<')

# More permissive tweet body extraction
_TWEET_BODY_RE = re.compile(
    r'class="(?:p-text|tweet-content)[^"]*"[^>]*>(.*?)</(?:div|p)>',
    re.DOTALL
)


def _strip_tags(html: str) -> str:
    return _TAG_RE.sub("", html).strip()


def _fetch_via_syndication(username: str, tweet_id: str) -> str | None:
    """Use Twitter syndication as final fallback."""
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            # Try to extract tweet text via multiple patterns
            bodies = _TWEET_BODY_RE.findall(content)
            if bodies:
                return " ".join(_strip_tags(b) for b in bodies[:5] if _strip_tags(b))
            # Fallback: strip all tags
            return _strip_tags(content)
    except Exception:
        return None


def extract_tweet(url: str) -> Document:
    m = re.match(r"https?://(?:twitter\.com|x\.com)/([^/?#]+)/status/(\d+)", url)
    if not m:
        raise ValueError(f"Not a valid tweet URL: {url}")
    username, tweet_id = m.group(1), m.group(2)

    # Try all Nitter instances
    html = None
    for instance in _NITTER_INSTANCES:
        try:
            req = urllib.request.Request(
                f"{instance}/{username}/status/{tweet_id}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    html = resp.read().decode("utf-8", errors="replace")
                    break
        except Exception:
            continue

    # Try syndication if all Nitter instances failed
    if html is None:
        syndication_text = _fetch_via_syndication(username, tweet_id)
        if syndication_text and syndication_text.strip():
            return Document(raw_text=syndication_text.strip(), content_type="tweet")

    # All sources failed — return graceful stub (don't raise)
    if html is None:
        return Document(raw_text=f"[NO_TWEET] {url}", content_type="tweet")

    # Parse HTML content
    bodies = _TWEET_BODY_RE.findall(html)
    handles = _HANDLE_RE.findall(html)
    names = _NAME_RE.findall(html)

    if not bodies:
        return Document(raw_text=f"[NO_TWEET] {url}", content_type="tweet")

    parts = []
    for i, body_html in enumerate(bodies[:10]):
        text = " ".join(_strip_tags(body_html).split())
        if not text:
            continue
        handle = handles[i].strip() if i < len(handles) else "unknown"
        name = names[i].strip() if i < len(names) else ""
        if i == 0:
            parts.append(f"@{handle} ({name})\n---\n{text}")
        else:
            parts.append(f"@{handle}: {text}")

    if not parts:
        return Document(raw_text=f"[NO_TWEET] {url}", content_type="tweet")

    raw_text = parts[0]
    if len(parts) > 1:
        raw_text += "\n\nReplies:\n" + "\n".join(parts[1:])

    return Document(raw_text=raw_text, content_type="tweet")
```

- [ ] **Step 4: Run Tweet tests — verify they pass**

```bash
pytest tests/test_tweet_ingester.py -v
```

- [ ] **Step 5: Commit**

```bash
git add ingesters/tweet.py tests/test_tweet_ingester.py
git commit -m "feat(tweet): expanded Nitter pool + CSS selectors + syndication fallback + graceful stub"
```

---

## Task 3: Run Full Test Suite

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest -v --tb=short
```

- [ ] **Step 2: Verify all tests pass, fix any regressions**

---

## Spec Coverage Check

| Spec Requirement | Task |
|-----------------|------|
| YouTube tiered subtitle fallback (3 tiers) | Task 1 |
| YouTube transcript API fallback | Task 1 |
| YouTube stub when all fail | Task 1 |
| Tweet expanded instance pool (8 instances) | Task 2 |
| Tweet updated CSS selectors | Task 2 |
| Tweet syndication RSS fallback | Task 2 |
| Tweet graceful stub instead of raise | Task 2 |
| All tests pass | Task 3 |
