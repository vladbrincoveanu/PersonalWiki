# YouTube Auto-Caption Tier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 4th yt-dlp tier targeting auto-generated English captions, with English-language filtering so non-English auto-captions are skipped and fall through to the next tier or API.

**Architecture:** `_SUBTITLE_TIERS` gains a 4th `auto-en` tier run after `all-subs`. New helper functions `_is_english_text()` and `_has_english_cues()` detect English-language captions via VTT lang attributes and Latin-script character ratio. `_try_subtitle_tiers` checks English detection for the `auto-en` tier and skips non-English results.

**Tech Stack:** stdlib `re`, `os`; existing `subprocess` for yt-dlp; no new dependencies.

---

## File Map

| File | Change |
|------|--------|
| `ingesters/youtube.py` | Add English detection helpers, add `auto-en` tier, update `_try_subtitle_tiers` |
| `tests/test_youtube_ingester.py` | Add auto-en tier tests, English detection tests |

---

## Task 1: Add English Detection Helpers

**Files:**
- Modify: `ingesters/youtube.py` — add `_is_english_text` and `_has_english_cues` before `_try_subtitle_tiers`
- Test: `tests/test_youtube_ingester.py` — add English detection unit tests

- [ ] **Step 1: Write failing tests**

```python
# tests/test_youtube_ingester.py — add these tests

def test_is_english_text_latin_ratio():
    """Latin-script-dominant text returns True."""
    from ingesters.youtube import _is_english_text
    assert _is_english_text("Hello world, this is English text.") is True
    assert _is_english_text("你好世界") is False  # Chinese — no Latin chars
    assert _is_english_text("Привет мир") is False  # Cyrillic
    # Mixed: should return True if ratio > 0.7
    assert _is_english_text("Hello 世界") is False  # 6/10 Latin = 0.6 < 0.7


def test_has_english_cues_with_lang_attribute():
    """VTT with lang=en-US in cue line returns True."""
    from ingesters.youtube import _has_english_cues
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:05.000 align:start position:50% line:84% size:100% font-family:\"YouTube Sans\" lang=en-US\nHello world"
    assert _has_english_cues(vtt) is True


def test_has_english_cues_falls_back_to_ratio():
    """VTT without lang attribute uses character ratio fallback."""
    from ingesters.youtube import _has_english_cues
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:05.000\nHello world this is English text"
    assert _has_english_cues(vtt) is True


def test_has_english_cues_rejects_non_english():
    """VTT with non-Latin text returns False."""
    from ingesters.youtube import _has_english_cues
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:05.000\nこれは日本語の字幕です"
    assert _has_english_cues(vtt) is False
```

- [ ] **Step 2: Run tests — verify they fail (helpers don't exist yet)**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_youtube_ingester.py -k "english" -v
```

- [ ] **Step 3: Add English detection helpers to youtube.py**

Add these functions right before `_try_subtitle_tiers`:

```python
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
```

- [ ] **Step 4: Run English detection tests — verify they pass**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_youtube_ingester.py -k "english" -v
```

- [ ] **Step 5: Commit**

```bash
git add ingesters/youtube.py tests/test_youtube_ingester.py
git commit -m "feat(youtube): add English caption detection helpers"
```

---

## Task 2: Add auto-en Tier and Update Tier Loop

**Files:**
- Modify: `ingesters/youtube.py` — update `_SUBTITLE_TIERS` and `_try_subtitle_tiers`
- Test: `tests/test_youtube_ingester.py` — add auto-en tier tests

- [ ] **Step 1: Write failing tests**

```python
# tests/test_youtube_ingester.py — add these tests

def test_auto_caption_tier_finds_english_auto_subs(monkeypatch, tmp_path):
    """auto-en tier with lang=en-US in VTT returns transcript."""
    import ingesters.youtube as yt

    vtt_content = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:05.000 align:start position:50% lang=en-US\n"
        "Hello from auto-generated captions\n\n"
        "00:00:05.000 --> 00:00:10.000 align:start position:50% lang=en-US\n"
        "This is English auto-captioned content"
    )
    vtt_file = tmp_path / "video.en.vtt"
    vtt_file.write_text(vtt_content)

    calls = []
    def mock_listdir(d):
        calls.append(d)
        return ["video.en.vtt"]

    monkeypatch.setattr("os.listdir", mock_listdir)

    result = yt._try_subtitle_tiers("https://youtube.com/watch?v=abc123DEF12", str(tmp_path))
    assert result is not None
    assert "Hello from auto-generated captions" in result


def test_auto_caption_tier_skips_non_english(monkeypatch, tmp_path):
    """auto-en tier with non-English VTT falls through to API."""
    import ingesters.youtube as yt

    # Japanese auto-captions — no lang=en, low Latin ratio
    vtt_content = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:05.000\n"
        "これは日本語の字幕です\n\n"
        "00:00:05.000 --> 00:00:10.000\n"
        "日本語の自動字幕"
    )
    vtt_file = tmp_path / "video.en.vtt"
    vtt_file.write_text(vtt_content)

    api_called = []
    def mock_transcript_api(video_id):
        api_called.append(video_id)
        return "API transcript fallback"

    monkeypatch.setattr("ingesters.youtube._run_yt_dlp", lambda *a, **kw: None)
    monkeypatch.setattr("ingesters.youtube._fetch_transcript_api", mock_transcript_api)

    doc = yt.extract_youtube("https://youtube.com/watch?v=abc123DEF12")
    # Should have fallen through to API
    assert api_called == ["abc123DEF12"]
    assert "API transcript fallback" in doc.raw_text
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_youtube_ingester.py -k "auto_caption" -v
```

- [ ] **Step 3: Update `_SUBTITLE_TIERS` and `_try_subtitle_tiers`**

In `ingesters/youtube.py`:

**Replace `_SUBTITLE_TIERS` with (add the 4th `auto-en` tier):**

```python
_SUBTITLE_TIERS = [
    {"args": ["--write-subs", "--write-auto-subs", "--sub-langs", "en",      "--sub-format", "vtt", "--skip-download"], "name": "en"},
    {"args": ["--write-subs", "--write-auto-subs", "--sub-langs", "en.*",    "--sub-format", "vtt", "--skip-download"], "name": "en-regex"},
    {"args": ["--write-subs", "--write-auto-subs", "--all-subs",                                             "--skip-download"], "name": "all"},
    {"args": ["--write-auto-subs", "--write-subs", "--sub-langs", "en",      "--sub-format", "vtt", "--skip-download"], "name": "auto-en"},
]
```

**Replace `_try_subtitle_tiers` with:**

```python
def _try_subtitle_tiers(url: str, tmpdir: str) -> str | None:
    """Try each subtitle tier. Returns transcript text or None."""
    for tier in _SUBTITLE_TIERS:
        vtt_files = _run_yt_dlp(tier["args"], tmpdir)
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
```

- [ ] **Step 4: Run auto_caption tests — verify they pass**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_youtube_ingester.py -k "auto_caption" -v
```

- [ ] **Step 5: Commit**

```bash
git add ingesters/youtube.py tests/test_youtube_ingester.py
git commit -m "feat(youtube): add auto-en caption tier with English language filtering"
```

---

## Task 3: Run Full Test Suite

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest -v --tb=short
```

- [ ] **Step 2: Verify all tests pass**

---

## Spec Coverage Check

| Spec Requirement | Task |
|-----------------|------|
| 4th auto-en tier | Task 2 |
| `lang=en` / `lang=en-US` detection in VTT | Task 1 |
| Latin-script character ratio fallback | Task 1 |
| Non-English auto-captions skip to next tier | Task 2 |
| All tests pass | Task 3 |
