# Ingesters Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tweet (Nitter), news (newspaper3k), and YouTube (yt-dlp) URL ingesters with smart pipeline routing and content-type-aware enrichment prompts.

**Architecture:** A `Document` dataclass in `ingesters/__init__.py` is the shared contract all ingesters return. `pipeline.py` gains an async `_route()` dispatcher that replaces the current `_is_pdf_url` / `extract_url` branching, plus a video transcript summarization step before enrichment. `core/minimax_client.py` gains a focused `summarize_transcript()` function and per-content-type instruction prefixes in `enrich()`.

**Tech Stack:** Python stdlib (`urllib`, `subprocess`, `re`, `html.parser`, `tempfile`), `newspaper3k` (new), `crawl4ai` (existing fallback), `yt-dlp` CLI (new), MiniMax API (existing), `pytest` + `pytest-asyncio` (existing)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `ingesters/__init__.py` | Modify | Add `Document` dataclass |
| `ingesters/tweet.py` | Create | Nitter HTTP fetch + regex HTML parse → Document |
| `ingesters/news.py` | Create | newspaper3k → crawl4ai fallback → paywall stub |
| `ingesters/youtube.py` | Create | yt-dlp VTT download + parse → Document |
| `ingesters/web.py` | Unchanged | Used as tier-2 fallback by `news.py` |
| `pipeline.py` | Modify | Add `_route()`, thread `content_type`, video summarize step |
| `core/minimax_client.py` | Modify | Add `summarize_transcript()`, adapt `_build_prompt()` per content type |
| `tests/test_tweet_ingester.py` | Create | Unit tests for tweet ingester |
| `tests/test_news_ingester.py` | Create | Unit tests for news ingester |
| `tests/test_youtube_ingester.py` | Create | Unit tests for YouTube ingester |
| `tests/test_router.py` | Create | Unit tests for `_route()` URL dispatch |
| `tests/test_summarize_transcript.py` | Create | Unit tests for `summarize_transcript()` |
| `tests/test_pipeline.py` | Modify | Update patches from `extract_url`/`_is_pdf_url` to `_route` |
| `requirements.txt` | Modify | Add `newspaper3k` and `yt-dlp` |

---

### Task 1: Add `Document` dataclass and install new dependencies

**Files:**
- Modify: `ingesters/__init__.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add dependencies to `requirements.txt`**

Add these two lines at the end of `requirements.txt`:

```
newspaper3k==0.2.8
yt-dlp==2024.11.18
```

- [ ] **Step 2: Install them**

```bash
pip install newspaper3k==0.2.8 yt-dlp==2024.11.18
```

Expected: both install without error. `python -c "from newspaper import Article; print('ok')"` prints `ok`. `yt-dlp --version` prints a version string.

- [ ] **Step 3: Write the failing test**

Create `tests/test_document.py`:

```python
from ingesters import Document


def test_document_defaults():
    doc = Document(raw_text="hello", content_type="article")
    assert doc.raw_text == "hello"
    assert doc.content_type == "article"
    assert doc.images == []


def test_document_with_images():
    doc = Document(raw_text="text", content_type="paper", images=[b"png1", b"png2"])
    assert len(doc.images) == 2
```

- [ ] **Step 4: Run test to verify it fails**

```bash
pytest tests/test_document.py -v
```

Expected: `ImportError` — `Document` not defined yet.

- [ ] **Step 5: Add `Document` to `ingesters/__init__.py`**

Replace the (empty) contents of `ingesters/__init__.py` with:

```python
from dataclasses import dataclass, field


@dataclass
class Document:
    raw_text: str
    content_type: str  # "paper" | "article" | "tweet" | "video"
    images: list[bytes] = field(default_factory=list)
```

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/test_document.py -v
```

Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add ingesters/__init__.py requirements.txt tests/test_document.py
git commit -m "feat: add Document dataclass and new ingester dependencies"
```

---

### Task 2: Tweet ingester (`ingesters/tweet.py`)

**Files:**
- Create: `ingesters/tweet.py`
- Create: `tests/test_tweet_ingester.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tweet_ingester.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from ingesters import Document


FAKE_NITTER_HTML = """
<html><body>
<div class="tweet-header">
  <a class="fullname" href="/hwchase17">Harrison Chase</a>
  <a class="username" href="/hwchase17">@hwchase17</a>
</div>
<div class="tweet-content media-body" dir="auto">
  Continual learning is the key missing piece for AI agents.
</div>
</body></html>
"""

FAKE_THREAD_HTML = """
<html><body>
<div class="tweet-header">
  <a class="fullname" href="/hwchase17">Harrison Chase</a>
  <a class="username" href="/hwchase17">@hwchase17</a>
</div>
<div class="tweet-content media-body" dir="auto">
  Continual learning is the key missing piece for AI agents.
</div>
<div class="tweet-header">
  <a class="fullname" href="/replier">Reply Person</a>
  <a class="username" href="/replier">@replier</a>
</div>
<div class="tweet-content media-body" dir="auto">
  Totally agree with this point.
</div>
</body></html>
"""


def _mock_urlopen(html: str, status: int = 200):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = html.encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_extract_tweet_returns_document():
    from ingesters.tweet import extract_tweet
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(FAKE_NITTER_HTML)):
        doc = extract_tweet("https://twitter.com/hwchase17/status/123456")
    assert isinstance(doc, Document)
    assert doc.content_type == "tweet"
    assert "hwchase17" in doc.raw_text
    assert "Continual learning" in doc.raw_text


def test_extract_tweet_x_com_url():
    from ingesters.tweet import extract_tweet
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(FAKE_NITTER_HTML)):
        doc = extract_tweet("https://x.com/hwchase17/status/123456")
    assert doc.content_type == "tweet"
    assert "Continual learning" in doc.raw_text


def test_extract_tweet_includes_thread_replies():
    from ingesters.tweet import extract_tweet
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(FAKE_THREAD_HTML)):
        doc = extract_tweet("https://twitter.com/hwchase17/status/123456")
    assert "Continual learning" in doc.raw_text
    assert "Totally agree" in doc.raw_text


def test_extract_tweet_rotates_on_instance_failure():
    from ingesters.tweet import extract_tweet
    side_effects = [
        Exception("Connection refused"),
        _mock_urlopen(FAKE_NITTER_HTML),
    ]
    with patch("urllib.request.urlopen", side_effect=side_effects):
        doc = extract_tweet("https://twitter.com/hwchase17/status/123456")
    assert "Continual learning" in doc.raw_text


def test_extract_tweet_raises_when_all_instances_fail():
    from ingesters.tweet import extract_tweet
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        with pytest.raises(ValueError, match="All Nitter instances"):
            extract_tweet("https://twitter.com/hwchase17/status/123456")


def test_extract_tweet_raises_on_invalid_url():
    from ingesters.tweet import extract_tweet
    with pytest.raises(ValueError, match="Not a valid tweet URL"):
        extract_tweet("https://example.com/not-a-tweet")
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_tweet_ingester.py -v
```

Expected: `ModuleNotFoundError: No module named 'ingesters.tweet'`

- [ ] **Step 3: Implement `ingesters/tweet.py`**

Create `ingesters/tweet.py`:

```python
import re
import urllib.request
from ingesters import Document

_NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.unixfox.eu",
    "https://nitter.net",
]

_TWEET_URL_RE = re.compile(
    r"https?://(?:twitter\.com|x\.com)/([^/?#]+)/status/(\d+)"
)
_CONTENT_RE = re.compile(
    r'class="tweet-content[^"]*"[^>]*>(.*?)</div>', re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_HANDLE_RE = re.compile(r'class="username"[^>]*>@?([^<\s]+)')
_NAME_RE = re.compile(r'class="fullname"[^>]*>([^<]+)<')


def _strip_tags(html: str) -> str:
    return _TAG_RE.sub("", html).strip()


def extract_tweet(url: str) -> Document:
    m = _TWEET_URL_RE.match(url)
    if not m:
        raise ValueError(f"Not a valid tweet URL: {url}")
    username, tweet_id = m.group(1), m.group(2)

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

    if html is None:
        raise ValueError(f"All Nitter instances unavailable for {url}")

    tweet_bodies = _CONTENT_RE.findall(html)
    handles = _HANDLE_RE.findall(html)
    names = _NAME_RE.findall(html)

    if not tweet_bodies:
        raise ValueError(f"No tweet content found at {url}")

    parts = []
    for i, body_html in enumerate(tweet_bodies[:10]):
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
        raise ValueError(f"No tweet content found at {url}")

    raw_text = parts[0]
    if len(parts) > 1:
        raw_text += "\n\nReplies:\n" + "\n".join(parts[1:])

    return Document(raw_text=raw_text, content_type="tweet")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_tweet_ingester.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add ingesters/tweet.py tests/test_tweet_ingester.py
git commit -m "feat: add tweet ingester via Nitter with instance rotation"
```

---

### Task 3: News ingester (`ingesters/news.py`)

**Files:**
- Create: `ingesters/news.py`
- Create: `tests/test_news_ingester.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_news_ingester.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from ingesters import Document


@pytest.mark.asyncio
async def test_extract_news_newspaper3k_success():
    from ingesters.news import extract_news
    long_text = "This is a full article with meaningful content. " * 10
    with patch("ingesters.news._newspaper_extract", return_value=long_text):
        doc = await extract_news("https://example.com/article")
    assert isinstance(doc, Document)
    assert doc.content_type == "article"
    assert "full article" in doc.raw_text


@pytest.mark.asyncio
async def test_extract_news_falls_back_to_crawl4ai_when_newspaper_short():
    from ingesters.news import extract_news
    crawl_text = "Full article content from crawl4ai JS rendering. " * 10
    with patch("ingesters.news._newspaper_extract", return_value="Too short."), \
         patch("ingesters.news.extract_url", AsyncMock(return_value=crawl_text)):
        doc = await extract_news("https://js-heavy.com/article")
    assert "crawl4ai JS rendering" in doc.raw_text


@pytest.mark.asyncio
async def test_extract_news_falls_back_to_crawl4ai_when_newspaper_raises():
    from ingesters.news import extract_news
    crawl_text = "Crawl4ai recovered the content just fine. " * 10
    with patch("ingesters.news._newspaper_extract", side_effect=Exception("download failed")), \
         patch("ingesters.news.extract_url", AsyncMock(return_value=crawl_text)):
        doc = await extract_news("https://example.com/article")
    assert "Crawl4ai recovered" in doc.raw_text


@pytest.mark.asyncio
async def test_extract_news_paywall_stub_when_both_tiers_return_short():
    from ingesters.news import extract_news
    with patch("ingesters.news._newspaper_extract", return_value="Subscribe now."), \
         patch("ingesters.news.extract_url", AsyncMock(return_value="Please log in.")):
        doc = await extract_news("https://nytimes.com/paywalled-article")
    assert doc.raw_text.startswith("[PAYWALLED]")
    assert "nytimes.com" in doc.raw_text
    assert doc.content_type == "article"


@pytest.mark.asyncio
async def test_extract_news_paywall_stub_does_not_raise():
    from ingesters.news import extract_news
    with patch("ingesters.news._newspaper_extract", return_value=""), \
         patch("ingesters.news.extract_url", AsyncMock(side_effect=Exception("403"))):
        doc = await extract_news("https://wsj.com/paywalled")
    assert doc.raw_text.startswith("[PAYWALLED]")
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_news_ingester.py -v
```

Expected: `ModuleNotFoundError: No module named 'ingesters.news'`

- [ ] **Step 3: Implement `ingesters/news.py`**

Create `ingesters/news.py`:

```python
import asyncio
from ingesters import Document
from ingesters.web import extract_url

_MIN_LENGTH = 200


async def extract_news(url: str) -> Document:
    # Tier 1: newspaper3k (sync — run in thread to avoid blocking event loop)
    try:
        text = await asyncio.to_thread(_newspaper_extract, url)
        if len(text.strip()) >= _MIN_LENGTH:
            return Document(raw_text=text, content_type="article")
    except Exception:
        pass

    # Tier 2: crawl4ai (async, already handles JS-heavy pages)
    try:
        text = await extract_url(url)
        if len(text.strip()) >= _MIN_LENGTH:
            return Document(raw_text=text, content_type="article")
    except Exception:
        pass

    # Tier 3: paywall fallback — write a stub note rather than raising
    return Document(
        raw_text=f"[PAYWALLED] {url}\n\nCould not extract full content.",
        content_type="article",
    )


def _newspaper_extract(url: str) -> str:
    from newspaper import Article
    article = Article(url)
    article.download()
    article.parse()
    return article.text
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_news_ingester.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add ingesters/news.py tests/test_news_ingester.py
git commit -m "feat: add news ingester with newspaper3k, crawl4ai fallback, paywall stub"
```

---

### Task 4: YouTube ingester (`ingesters/youtube.py`)

**Files:**
- Create: `ingesters/youtube.py`
- Create: `tests/test_youtube_ingester.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_youtube_ingester.py`:

```python
import os
import pytest
from unittest.mock import patch, MagicMock
from contextlib import contextmanager
from ingesters import Document


SAMPLE_VTT = """\
WEBVTT

00:00:01.000 --> 00:00:04.000
The key insight here is continual learning.

00:00:04.000 --> 00:00:07.000
The key insight here is continual learning.

00:00:07.000 --> 00:00:10.000
Agents must update their knowledge over time.
"""


def test_parse_vtt_strips_timestamps():
    from ingesters.youtube import _parse_vtt
    result = _parse_vtt(SAMPLE_VTT)
    assert "-->" not in result
    assert "WEBVTT" not in result


def test_parse_vtt_deduplicates_repeated_lines():
    from ingesters.youtube import _parse_vtt
    result = _parse_vtt(SAMPLE_VTT)
    # "The key insight" appears twice in the VTT but once after dedup
    assert result.count("key insight") == 1


def test_parse_vtt_preserves_content():
    from ingesters.youtube import _parse_vtt
    result = _parse_vtt(SAMPLE_VTT)
    assert "continual learning" in result
    assert "Agents must update" in result


def test_extract_youtube_returns_transcript(tmp_path, monkeypatch):
    from ingesters.youtube import extract_youtube

    vtt_file = tmp_path / "abc123.en.vtt"
    vtt_file.write_text(SAMPLE_VTT)

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: MagicMock(returncode=0))

    @contextmanager
    def mock_tmpdir():
        yield str(tmp_path)

    import ingesters.youtube as yt_module
    monkeypatch.setattr(yt_module.tempfile, "TemporaryDirectory", lambda: mock_tmpdir())

    doc = extract_youtube("https://youtube.com/watch?v=abc123")
    assert isinstance(doc, Document)
    assert doc.content_type == "video"
    assert "continual learning" in doc.raw_text


def test_extract_youtube_no_subtitles_returns_stub(tmp_path, monkeypatch):
    from ingesters.youtube import extract_youtube

    # tmp_path is empty — no .vtt file produced
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: MagicMock(returncode=0))

    @contextmanager
    def mock_tmpdir():
        yield str(tmp_path)

    import ingesters.youtube as yt_module
    monkeypatch.setattr(yt_module.tempfile, "TemporaryDirectory", lambda: mock_tmpdir())

    doc = extract_youtube("https://youtube.com/watch?v=nosubs")
    assert doc.raw_text.startswith("[NO_TRANSCRIPT]")
    assert doc.content_type == "video"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_youtube_ingester.py -v
```

Expected: `ModuleNotFoundError: No module named 'ingesters.youtube'`

- [ ] **Step 3: Implement `ingesters/youtube.py`**

Create `ingesters/youtube.py`:

```python
import os
import re
import subprocess
import tempfile
from ingesters import Document

_TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->.*$", re.MULTILINE)
_TAG_RE = re.compile(r"<[^>]+>")
_CUE_SETTING_RE = re.compile(r"^(?:align|line|position|size|vertical):.*$", re.MULTILINE)


def _parse_vtt(vtt_text: str) -> str:
    # Remove WEBVTT header block
    text = re.sub(r"^WEBVTT.*?\n\n", "", vtt_text, count=1, flags=re.DOTALL)
    # Remove timestamp cue lines
    text = _TIMESTAMP_RE.sub("", text)
    # Remove cue setting lines (align:, line:, etc.)
    text = _CUE_SETTING_RE.sub("", text)
    # Remove inline HTML tags (<c>, <b>, <i>, timestamps like <00:00:01.000>)
    text = _TAG_RE.sub("", text)
    # Split, strip, drop blanks, deduplicate consecutive identical lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    deduped: list[str] = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)
    return " ".join(deduped)


def extract_youtube(url: str) -> Document:
    with tempfile.TemporaryDirectory() as tmpdir:
        output_template = os.path.join(tmpdir, "%(id)s")
        cmd = [
            "yt-dlp",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", "en",
            "--sub-format", "vtt",
            "--skip-download",
            "--output", output_template,
            "--quiet",
            url,
        ]
        subprocess.run(cmd, capture_output=True, timeout=60)

        vtt_files = [f for f in os.listdir(tmpdir) if f.endswith(".vtt")]
        if not vtt_files:
            return Document(raw_text=f"[NO_TRANSCRIPT] {url}", content_type="video")

        with open(os.path.join(tmpdir, vtt_files[0]), encoding="utf-8") as f:
            vtt_text = f.read()

        transcript = _parse_vtt(vtt_text)
        if not transcript.strip():
            return Document(raw_text=f"[NO_TRANSCRIPT] {url}", content_type="video")

        return Document(raw_text=transcript, content_type="video")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_youtube_ingester.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add ingesters/youtube.py tests/test_youtube_ingester.py
git commit -m "feat: add YouTube ingester via yt-dlp transcript with VTT parsing"
```

---

### Task 5: Router and pipeline update (`pipeline.py`)

**Files:**
- Modify: `pipeline.py`
- Create: `tests/test_router.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing router tests**

Create `tests/test_router.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from ingesters import Document
from ingesters.pdf import PdfExtractResult


@pytest.mark.asyncio
async def test_route_twitter_url():
    from pipeline import _route
    mock_doc = Document(raw_text="tweet text", content_type="tweet")
    with patch("pipeline.extract_tweet", return_value=mock_doc):
        doc = await _route("https://twitter.com/user/status/123")
    assert doc.content_type == "tweet"


@pytest.mark.asyncio
async def test_route_x_com_url():
    from pipeline import _route
    mock_doc = Document(raw_text="tweet text", content_type="tweet")
    with patch("pipeline.extract_tweet", return_value=mock_doc):
        doc = await _route("https://x.com/user/status/456")
    assert doc.content_type == "tweet"


@pytest.mark.asyncio
async def test_route_youtube_com_url():
    from pipeline import _route
    mock_doc = Document(raw_text="transcript", content_type="video")
    with patch("pipeline.extract_youtube", return_value=mock_doc):
        doc = await _route("https://www.youtube.com/watch?v=abc123")
    assert doc.content_type == "video"


@pytest.mark.asyncio
async def test_route_youtu_be_url():
    from pipeline import _route
    mock_doc = Document(raw_text="transcript", content_type="video")
    with patch("pipeline.extract_youtube", return_value=mock_doc):
        doc = await _route("https://youtu.be/abc123")
    assert doc.content_type == "video"


@pytest.mark.asyncio
async def test_route_news_url():
    from pipeline import _route
    mock_doc = Document(raw_text="article text", content_type="article")
    with patch("pipeline.extract_news", AsyncMock(return_value=mock_doc)):
        doc = await _route("https://techcrunch.com/2026/01/some-article")
    assert doc.content_type == "article"


@pytest.mark.asyncio
async def test_route_pdf_url():
    from pipeline import _route
    fake_result = PdfExtractResult(
        markdown="# Paper content here",
        low_quality=False,
        images=[b"fakepng"],
    )
    with patch("pipeline._is_pdf_url", return_value=True), \
         patch("urllib.request.urlretrieve"), \
         patch("pipeline.extract_pdf_full", return_value=fake_result):
        doc = await _route("https://arxiv.org/pdf/2309.06180.pdf")
    assert doc.content_type == "paper"
    assert doc.raw_text == "# Paper content here"
    assert doc.images == [b"fakepng"]
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_router.py -v
```

Expected: `ImportError` — `_route` not defined in `pipeline`.

- [ ] **Step 3: Update `pipeline.py`**

Replace the current contents of `pipeline.py` with:

```python
import asyncio
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import AsyncGenerator
from urllib.parse import urlparse

from config import TOP_K_SIMILAR, MAX_EMBED_CHARS
from core.embeddings import embed
from core.vector_store import get_store
from core.minimax_client import enrich
from ingesters import Document
from ingesters.tweet import extract_tweet
from ingesters.news import extract_news
from ingesters.youtube import extract_youtube
from ingesters.pdf import extract_pdf_full
from vault.writer import write_note


def _is_pdf_url(url: str) -> bool:
    """Return True if the URL serves a PDF (by extension or Content-Type)."""
    if url.lower().split("?")[0].endswith(".pdf"):
        return True
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as resp:
            ct = resp.headers.get("Content-Type", "")
            return "application/pdf" in ct
    except Exception:
        return False


async def _route(url: str) -> Document:
    """Dispatch a URL to the correct ingester and return a Document."""
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if _is_pdf_url(url):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
            await asyncio.to_thread(urllib.request.urlretrieve, url, tmp_path)
            result = await asyncio.to_thread(extract_pdf_full, tmp_path)
            return Document(
                raw_text=result.markdown,
                content_type="paper",
                images=result.images,
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    if host in ("twitter.com", "x.com") and "/status/" in parsed.path:
        return await asyncio.to_thread(extract_tweet, url)

    if host in ("youtube.com", "www.youtube.com", "youtu.be"):
        return await asyncio.to_thread(extract_youtube, url)

    return await extract_news(url)


async def run_pipeline(
    url: str | None = None,
    pdf_path: str | None = None,
) -> AsyncGenerator[str, None]:
    store = get_store()
    source = url or pdf_path

    # Duplicate check
    if url and store.exists(url):
        yield "Warning: Note for this URL already exists. Skipping."
        return

    # Step 1: Extract
    yield "Extracting content..."
    images: list[bytes] = []
    content_type = "article"
    try:
        if url:
            doc = await _route(url)
            raw_text = doc.raw_text
            images = doc.images
            content_type = doc.content_type
        else:
            result = await asyncio.to_thread(extract_pdf_full, pdf_path)
            raw_text = result.markdown
            images = result.images
            content_type = "paper"
    except Exception as e:
        yield f"Error during extraction: {e}"
        return

    # Step 2: Find similar
    yield "Finding similar notes..."
    vector = embed(raw_text[:MAX_EMBED_CHARS])
    similar = store.search(vector, top_k=TOP_K_SIMILAR)
    similar_titles = [
        s["metadata"].get("title", Path(s["path"]).stem)
        for s in similar
        if isinstance(s.get("metadata"), dict)
    ]
    yield f"Finding similar notes ({len(similar)} found)..."

    # Step 3: Enrich
    yield "Enriching with Minimax..."
    note = await asyncio.to_thread(enrich, raw_text, similar_titles, source, content_type)

    # Step 4: Write
    yield "Saving note..."
    path = write_note(note, source=source, images=images)

    # Step 5: Index
    yield "Indexing..."
    index_meta = {k: v for k, v in note.items() if k != "raw_text"}
    index_meta["_file_path"] = path
    store.upsert(
        path=source,
        text=raw_text,
        vector=vector,
        links=note.get("cross_links", []),
        metadata=index_meta,
    )

    stem = Path(path).name
    yield f"Saved -> notes/{stem}"
```

- [ ] **Step 4: Run router tests**

```bash
pytest tests/test_router.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Update `tests/test_pipeline.py` to patch `_route` instead of `extract_url` / `_is_pdf_url`**

The existing tests patch `pipeline.extract_url` and `pipeline._is_pdf_url`. Those are no longer the right patch targets. Replace the entire contents of `tests/test_pipeline.py` with:

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from ingesters import Document
from ingesters.pdf import PdfExtractResult


@pytest.mark.asyncio
async def test_pipeline_url_yields_progress_steps():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.search.return_value = [{"metadata": {"title": "Existing Note"}, "path": "notes/existing.md"}]
    mock_store.exists.return_value = False

    mock_doc = Document(raw_text="Raw content from URL.", content_type="article")

    with patch("pipeline._route", AsyncMock(return_value=mock_doc)), \
         patch("pipeline.embed", return_value=[0.1] * 384), \
         patch("pipeline.get_store", return_value=mock_store), \
         patch("pipeline.enrich", return_value={
             "title": "Test Note", "type": "article", "tags": ["ai"],
             "summary": "Summary.", "key_facts": ["Fact"],
             "cross_links": ["existing-note"], "raw_text": "Raw.",
             "entities": [], "figure_captions": [], "why_saved_hint": "",
             "error": False,
         }), \
         patch("pipeline.write_note", return_value="/vault/notes/test-note.md"):

        messages = []
        async for msg in run_pipeline(url="https://example.com"):
            messages.append(msg)

    assert any("Extracting" in m for m in messages)
    assert any("similar" in m.lower() for m in messages)
    assert any("Minimax" in m for m in messages)
    assert any("Saved" in m for m in messages)


@pytest.mark.asyncio
async def test_pipeline_duplicate_url_detected():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = True

    with patch("pipeline.get_store", return_value=mock_store):
        messages = []
        async for msg in run_pipeline(url="https://already-ingested.com"):
            messages.append(msg)

    assert any("already exists" in m.lower() for m in messages)
    assert not any("Extracting" in m for m in messages)


@pytest.mark.asyncio
async def test_pipeline_handles_extraction_error():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False

    with patch("pipeline.get_store", return_value=mock_store), \
         patch("pipeline._route", AsyncMock(side_effect=ValueError("unreachable"))):

        messages = []
        async for msg in run_pipeline(url="https://bad-url.com"):
            messages.append(msg)

    assert any("Error" in m or "error" in m for m in messages)


@pytest.mark.asyncio
async def test_pipeline_pdf_url_passes_images_to_writer():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.exists.return_value = False
    mock_store.search.return_value = []

    mock_doc = Document(
        raw_text="# Paper\n\n<!-- image --> some content " + "x" * 300,
        content_type="paper",
        images=[b"fakepng1", b"fakepng2"],
    )

    written_images = []

    def capture_write_note(note, source, images=()):
        written_images.extend(images)
        return "/vault/notes/paper.md"

    with patch("pipeline._route", AsyncMock(return_value=mock_doc)), \
         patch("pipeline.get_store", return_value=mock_store), \
         patch("pipeline.embed", return_value=[0.1] * 384), \
         patch("pipeline.enrich", return_value={
             "title": "Paper", "type": "paper", "tags": [],
             "summary": "S.", "key_facts": [], "cross_links": [],
             "raw_text": "raw", "entities": [], "figure_captions": [],
             "why_saved_hint": "", "error": False,
         }), \
         patch("pipeline.write_note", side_effect=capture_write_note):

        messages = []
        async for msg in run_pipeline(url="https://arxiv.org/pdf/2510.18518"):
            messages.append(msg)

    assert written_images == [b"fakepng1", b"fakepng2"]
    assert any("Saved" in m for m in messages)
```

- [ ] **Step 6: Run the full updated pipeline test suite**

```bash
pytest tests/test_pipeline.py tests/test_router.py -v
```

Expected: all tests pass (4 pipeline + 6 router = 10 passed).

- [ ] **Step 7: Run the full test suite to check for regressions**

```bash
pytest -v
```

Expected: all previously passing tests still pass. Fix any failures before committing.

- [ ] **Step 8: Commit**

```bash
git add pipeline.py tests/test_router.py tests/test_pipeline.py
git commit -m "feat: add _route() dispatcher and thread content_type through pipeline"
```

---

### Task 6: Prompt awareness and transcript summarization

**Files:**
- Modify: `core/minimax_client.py`
- Modify: `pipeline.py`
- Create: `tests/test_summarize_transcript.py`
- Modify: `tests/test_minimax_client.py` (add `content_type` coverage)

- [ ] **Step 1: Write failing tests for `summarize_transcript`**

Create `tests/test_summarize_transcript.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


def test_summarize_transcript_returns_plain_text():
    from core.minimax_client import summarize_transcript
    mock_response = {
        "choices": [{"message": {"content": "A concise summary of the video."}}]
    }
    with patch("core.minimax_client.MINIMAX_API_KEY", "test-key"), \
         patch("core.minimax_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
        )
        result = summarize_transcript(
            "Long transcript text about agents...",
            "https://youtube.com/watch?v=abc",
        )
    assert result == "A concise summary of the video."


def test_summarize_transcript_fallback_on_api_error():
    from core.minimax_client import summarize_transcript
    long_transcript = "Word " * 2000  # ~10000 chars
    with patch("core.minimax_client.MINIMAX_API_KEY", "test-key"), \
         patch("core.minimax_client.requests.post", side_effect=Exception("timeout")):
        result = summarize_transcript(long_transcript, "https://youtube.com/watch?v=abc")
    assert result == long_transcript[:6000]


def test_summarize_transcript_no_api_key_returns_truncated():
    from core.minimax_client import summarize_transcript
    with patch("core.minimax_client.MINIMAX_API_KEY", ""):
        result = summarize_transcript("Some transcript content.", "https://youtube.com/watch?v=abc")
    assert result == "Some transcript content."


def test_summarize_transcript_truncates_long_input_to_40k():
    from core.minimax_client import summarize_transcript
    very_long = "x " * 30000  # 60000 chars
    captured = {}

    def capture_post(url, **kwargs):
        captured["payload"] = kwargs.get("json", {})
        return MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "Summary."}}]},
        )

    with patch("core.minimax_client.MINIMAX_API_KEY", "test-key"), \
         patch("core.minimax_client.requests.post", side_effect=capture_post):
        summarize_transcript(very_long, "https://youtube.com/watch?v=abc")

    user_content = captured["payload"]["messages"][1]["content"]
    # The prompt includes the transcript truncated to 40000 chars
    assert len(user_content) < 45000
```

- [ ] **Step 2: Write failing tests for `content_type` prompt adaptation**

Add these tests to `tests/test_minimax_client.py` (append to the existing file):

```python
def test_build_prompt_includes_tweet_focus():
    from core.minimax_client import _build_prompt
    prompt = _build_prompt(
        raw_text="Thread about agents.",
        similar_titles=[],
        source="https://twitter.com/user/status/1",
        content_type="tweet",
    )
    assert "exact argument" in prompt.lower() or "claims" in prompt.lower()


def test_build_prompt_includes_video_focus():
    from core.minimax_client import _build_prompt
    prompt = _build_prompt(
        raw_text="This is a transcript summary.",
        similar_titles=[],
        source="https://youtube.com/watch?v=abc",
        content_type="video",
    )
    assert "transcript" in prompt.lower() or "thesis" in prompt.lower()


def test_build_prompt_default_content_type_is_article():
    from core.minimax_client import _build_prompt
    prompt = _build_prompt(
        raw_text="Some article text.",
        similar_titles=[],
        source="https://example.com",
    )
    # Should not crash and should still include raw text
    assert "Some article text." in prompt
```

- [ ] **Step 3: Run to verify failures**

```bash
pytest tests/test_summarize_transcript.py tests/test_minimax_client.py -v
```

Expected: `test_summarize_transcript.py` errors with `ImportError` (function not defined yet); existing `test_minimax_client.py` tests pass; new `_build_prompt` tests fail because `content_type` param doesn't exist yet.

- [ ] **Step 4: Update `core/minimax_client.py`**

Replace the entire contents of `core/minimax_client.py` with:

```python
import json
import logging
import requests
from config import MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_API_URL

_logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a knowledge curator. Given raw text from a source, extract and structure it into a research note.
Always respond with valid JSON only — no markdown fences, no explanation."""

_CONTENT_TYPE_FOCUS = {
    "paper": "Focus on methodology, findings, and limitations.",
    "article": "Focus on the main argument and key evidence.",
    "tweet": "Capture the exact argument and any specific claims or data points made.",
    "video": "This is a transcript summary. Focus on the speaker's core thesis and concrete examples.",
}

_NOTE_TEMPLATE = """
{focus}

Analyze this content and respond with JSON in exactly this structure:
{{
  "title": "concise descriptive title",
  "type": "paper|article|video|personal",
  "tags": ["tag1", "tag2", "tag3"],
  "summary": "2-3 sentence synthesis of the main insight",
  "key_facts": ["fact 1", "fact 2", "fact 3"],
  "cross_links": ["existing-note-slug-1", "existing-note-slug-2"],
  "entities": [
    {{"name": "Display Name", "slug": "display-name", "type": "concept|person|institution|dataset|method"}}
  ],
  "figure_captions": ["one-line caption for figure 1 inferred from surrounding text", "caption for figure 2"],
  "why_saved_hint": "one sentence about why this source is worth keeping"
}}

Rules:
- entities: extract recurring concepts, people, institutions, datasets, and methods that deserve their own notes. slug must be lowercase with hyphens (e.g. "MIMIC-IV" → "mimic-iv"). Only include entities that appear meaningfully in the content.
- figure_captions: the raw content contains <!-- image --> placeholders where figures appear. Generate one caption per placeholder IN ORDER based on the surrounding text. Return an empty list if there are no <!-- image --> placeholders.
- cross_links: use slugs of existing notes listed below only if genuinely relevant.
- why_saved_hint: one sentence starter for a personal note about relevance — be specific, not generic.

Source: {source}

Existing notes in my vault that may be related (use their slugs for cross_links only if genuinely relevant):
{similar}

Raw content to analyze:
{raw_text}
"""

_SUMMARIZE_PROMPT = """Summarize this video transcript in approximately 800 words.
Preserve the speaker's core thesis, specific claims, concrete examples, and any data or frameworks introduced.
Do not add commentary or opinions. Return plain text only — no JSON, no markdown headings.

Source: {source}

Transcript:
{transcript}
"""


def _build_prompt(
    raw_text: str,
    similar_titles: list[str],
    source: str,
    content_type: str = "article",
) -> str:
    focus = _CONTENT_TYPE_FOCUS.get(content_type, _CONTENT_TYPE_FOCUS["article"])
    similar_str = "\n".join(f"- {t}" for t in similar_titles) if similar_titles else "(none yet)"
    return _NOTE_TEMPLATE.format(
        focus=focus,
        source=source,
        similar=similar_str,
        raw_text=raw_text[:6000],
    )


def enrich(
    raw_text: str,
    similar_titles: list[str],
    source: str,
    content_type: str = "article",
) -> dict:
    if not MINIMAX_API_KEY:
        _logger.warning("MINIMAX_API_KEY is not set — returning fallback for source=%s", source)
        return {
            "title": "Untitled",
            "type": "article",
            "tags": [],
            "summary": "",
            "key_facts": [],
            "cross_links": [],
            "entities": [],
            "figure_captions": [],
            "why_saved_hint": "",
            "raw_text": raw_text,
            "error": True,
        }
    prompt = _build_prompt(raw_text, similar_titles, source, content_type)
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MINIMAX_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code") and base_resp["status_code"] != 0:
            raise ValueError(f"Minimax API error {base_resp['status_code']}: {base_resp.get('status_msg')}")
        if "choices" not in data:
            _logger.error("Minimax unexpected response for source=%s: %s", source, data)
            raise ValueError(f"No 'choices' in Minimax response: {data}")
        content = data["choices"][0]["message"]["content"]
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(content)
        data.setdefault("entities", [])
        data.setdefault("figure_captions", [])
        data.setdefault("why_saved_hint", "")
        data.setdefault("raw_text", raw_text)
        data.setdefault("error", False)
        return data
    except Exception as e:
        _logger.warning("Minimax enrich failed for source=%s: %s", source, e)
        return {
            "title": "Untitled",
            "type": "article",
            "tags": [],
            "summary": "",
            "key_facts": [],
            "cross_links": [],
            "entities": [],
            "figure_captions": [],
            "why_saved_hint": "",
            "raw_text": raw_text,
            "error": True,
        }


def summarize_transcript(raw_text: str, source: str) -> str:
    """Summarize a long video transcript to ~800 words before enrichment.

    Falls back to the first 6000 chars of raw_text if the API call fails or
    no API key is configured.
    """
    if not MINIMAX_API_KEY:
        return raw_text[:6000]
    prompt = _SUMMARIZE_PROMPT.format(
        source=source,
        transcript=raw_text[:40000],
    )
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MINIMAX_MODEL,
        "messages": [
            {"role": "system", "content": "You are a precise summarizer. Follow instructions exactly."},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        _logger.warning("summarize_transcript failed for source=%s: %s", source, e)
        return raw_text[:6000]
```

- [ ] **Step 5: Run the minimax tests to verify they pass**

```bash
pytest tests/test_summarize_transcript.py tests/test_minimax_client.py -v
```

Expected: all tests pass (4 summarize + 8 minimax = 12 passed).

- [ ] **Step 6: Add the video summarize step to `pipeline.py`**

In `pipeline.py`, import `summarize_transcript` at the top (add to the existing imports from `core.minimax_client`):

```python
from core.minimax_client import enrich, summarize_transcript
```

Then, between "Step 1: Extract" and "Step 2: Find similar", add the video summarize step. The full updated block in `run_pipeline` after the extraction `try/except`:

```python
    # Step 1b: Summarize transcript for video content
    if content_type == "video" and not raw_text.startswith("[NO_TRANSCRIPT]"):
        yield "Summarizing transcript..."
        raw_text = await asyncio.to_thread(summarize_transcript, raw_text, source)

    # Step 2: Find similar
    yield "Finding similar notes..."
```

- [ ] **Step 7: Add a pipeline test for the video summarize step**

Append to `tests/test_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_pipeline_video_summarizes_transcript():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.search.return_value = []
    mock_store.exists.return_value = False

    mock_doc = Document(raw_text="Raw long transcript text.", content_type="video")

    with patch("pipeline._route", AsyncMock(return_value=mock_doc)), \
         patch("pipeline.summarize_transcript", return_value="Concise summary of the talk.") as mock_summarize, \
         patch("pipeline.embed", return_value=[0.1] * 384), \
         patch("pipeline.get_store", return_value=mock_store), \
         patch("pipeline.enrich", return_value={
             "title": "Talk", "type": "video", "tags": [],
             "summary": "S.", "key_facts": [], "cross_links": [],
             "raw_text": "raw", "entities": [], "figure_captions": [],
             "why_saved_hint": "", "error": False,
         }), \
         patch("pipeline.write_note", return_value="/vault/notes/talk.md"):

        messages = []
        async for msg in run_pipeline(url="https://youtube.com/watch?v=abc"):
            messages.append(msg)

    mock_summarize.assert_called_once()
    assert any("Summarizing" in m for m in messages)
    assert any("Saved" in m for m in messages)


@pytest.mark.asyncio
async def test_pipeline_no_transcript_skips_summarize():
    from pipeline import run_pipeline

    mock_store = MagicMock()
    mock_store.search.return_value = []
    mock_store.exists.return_value = False

    mock_doc = Document(
        raw_text="[NO_TRANSCRIPT] https://youtube.com/watch?v=nosubs",
        content_type="video",
    )

    with patch("pipeline._route", AsyncMock(return_value=mock_doc)), \
         patch("pipeline.summarize_transcript") as mock_summarize, \
         patch("pipeline.embed", return_value=[0.1] * 384), \
         patch("pipeline.get_store", return_value=mock_store), \
         patch("pipeline.enrich", return_value={
             "title": "No Subs", "type": "video", "tags": [],
             "summary": "", "key_facts": [], "cross_links": [],
             "raw_text": "raw", "entities": [], "figure_captions": [],
             "why_saved_hint": "", "error": False,
         }), \
         patch("pipeline.write_note", return_value="/vault/notes/nosubs.md"):

        async for _ in run_pipeline(url="https://youtube.com/watch?v=nosubs"):
            pass

    mock_summarize.assert_not_called()
```

- [ ] **Step 8: Run the full test suite**

```bash
pytest -v
```

Expected: all tests pass. If any existing test fails due to the `_build_prompt` signature change, check that it calls `_build_prompt` without `content_type` — the default `"article"` makes it backward compatible.

- [ ] **Step 9: Commit**

```bash
git add core/minimax_client.py pipeline.py tests/test_summarize_transcript.py tests/test_minimax_client.py tests/test_pipeline.py
git commit -m "feat: add summarize_transcript and content-type-aware enrichment prompts"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| `Document` dataclass | Task 1 |
| Tweet ingester via Nitter, 4 instances, rotate on failure | Task 2 |
| Full thread capture (up to 10 tweets) | Task 2 |
| News ingester via newspaper3k | Task 3 |
| News fallback to crawl4ai | Task 3 |
| News paywall stub with `[PAYWALLED]` flag | Task 3 |
| YouTube ingester via yt-dlp VTT | Task 4 |
| VTT timestamp stripping and deduplication | Task 4 |
| `[NO_TRANSCRIPT]` stub for no-subtitle case | Task 4 |
| Router `_route()` with 5 URL patterns | Task 5 |
| `content_type` threaded through pipeline | Task 5 |
| `enrich()` gains `content_type` param with default | Task 6 |
| Per-content-type instruction prefixes | Task 6 |
| `summarize_transcript()` with 40k char truncation | Task 6 |
| Summarize step in pipeline for video, skipped for `[NO_TRANSCRIPT]` | Task 6 |
| Graceful fallback on summarize API failure | Task 6 |
| `requirements.txt` updated | Task 1 |
| All ingesters tested | Tasks 2–4 |
| Router tested | Task 5 |
| Pipeline tests updated | Task 5 |
