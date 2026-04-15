# Ingesters Expansion Design

**Date:** 2026-04-12
**Status:** Approved

## Overview

Add three new URL ingesters (tweet, news, YouTube) and update the pipeline router and enrichment prompt to handle them. All ingesters produce a `Document` dataclass that flows unchanged into the existing enrichment pipeline.

The existing `ingesters/web.py` (crawl4ai) is demoted from primary to fallback — it becomes tier 2 inside the news ingester.

## Shared Contract: `Document` dataclass

Introduce in `ingesters/__init__.py`:

```python
@dataclass
class Document:
    raw_text: str
    content_type: str  # "paper" | "article" | "tweet" | "video"
    images: list[bytes] = field(default_factory=list)
```

Every ingester returns a `Document`. The pipeline operates on `Document` objects after routing.

## Task A — Tweet ingester (`ingesters/tweet.py`)

**Function:** `extract_tweet(url: str) -> Document`

**Approach:** Nitter (open-source X frontend). No API key, no X rate limits.

**Details:**
- Parse tweet ID and username from `twitter.com/*/status/<id>` or `x.com/*/status/<id>` URL patterns
- Try 4 hardcoded public Nitter instances in order:
  1. `https://nitter.poast.org`
  2. `https://nitter.privacydev.net`
  3. `https://nitter.unixfox.eu`
  4. `https://nitter.net`
- Rotate on connection failure or non-200 response
- Fetch `{instance}/{user}/status/{id}` and parse HTML with stdlib `html.parser`
- Extract: author display name, handle, tweet body text, reply chain (up to 10 tweets)
- Format as plain text:
  ```
  @handle (Display Name)
  ---
  {tweet body}

  Replies:
  @reply_handle: {reply text}
  ...
  ```
- Return `Document(raw_text=formatted_text, content_type="tweet")`
- If all 4 instances fail: raise `ValueError("All Nitter instances unavailable for {url}")`

**Dependencies:** stdlib only (`urllib.request`, `html.parser`)

## Task B — News ingester (`ingesters/news.py`)

**Function:** `extract_news(url: str) -> Document`

**Approach:** Three-tier fallback. Newspaper3k is fast and handles most news sites; crawl4ai handles JS-heavy pages; paywall fallback prevents hard failures.

**Details:**

**Tier 1 — newspaper3k:**
- `Article(url); article.download(); article.parse()`
- Success if `len(article.text.strip()) >= 200`

**Tier 2 — crawl4ai (existing `ingesters/web.py`):**
- Call `extract_url(url)` from the existing web ingester
- Success if `len(result.strip()) >= 200`

**Tier 3 — Paywall fallback:**
- Both tiers returned < 200 chars
- Return `Document(raw_text="[PAYWALLED] {url}\n\nCould not extract full content.", content_type="article")`
- Does not raise — pipeline continues and writes a stub note with the `[PAYWALLED]` flag visible

**Return:** `Document(raw_text=extracted_text, content_type="article")`

**Dependencies:** `newspaper3k` (new), `crawl4ai` (existing)

## Task C — YouTube ingester (`ingesters/youtube.py`)

**Function:** `extract_youtube(url: str) -> Document`

**Approach:** `yt-dlp` subtitle download only — no audio, no Whisper.

**Details:**
- Run `yt-dlp --write-subs --write-auto-subs --sub-langs en --sub-format vtt --skip-download --output /tmp/{video_id} {url}`
- Locate the downloaded `.vtt` file
- Strip VTT timestamps and formatting tags with regex → plain transcript text
- Deduplicate repeated lines (VTT auto-subs repeat lines across overlapping captions)
- If no subtitle file produced: return `Document(raw_text="[NO_TRANSCRIPT] {url}", content_type="video")`
- Return `Document(raw_text=transcript_text, content_type="video")`
- Clean up temp files in `finally`

**Dependencies:** `yt-dlp` (new, CLI tool — must be installed in environment)

## Task D — Router update (`pipeline.py`)

**Function:** `async def _route(url: str) -> Document` (replaces current `_is_pdf_url` + ingester dispatch block)

`_route()` is async because `extract_news()` may fall back to `extract_url()` (crawl4ai), which is async. PDF and tweet paths use `asyncio.to_thread` internally for their blocking calls.

**Routing table (evaluated in order):**

| Condition | Action |
|---|---|
| URL ends with `.pdf` OR `Content-Type: application/pdf` | `await asyncio.to_thread(extract_pdf_full, ...)` → `Document(raw_text=result.markdown, content_type="paper", images=result.images)` |
| host is `twitter.com` or `x.com` and path matches `*/status/*` | `await asyncio.to_thread(extract_tweet, url)` |
| host is `youtube.com` or `youtu.be` | `await asyncio.to_thread(extract_youtube, url)` |
| everything else | `await extract_news(url)` |

**Pipeline changes:**
- Import `Document` from `ingesters`
- Replace the `if url and _is_pdf_url(url): ... elif url: raw_text = await extract_url(url)` block with `doc = await _route(url)`
- `raw_text = doc.raw_text`, `images = doc.images`, `content_type = doc.content_type`
- Pass `content_type` through to `enrich()` and the new `summarize_transcript()` call

**Note:** `extract_news()` must be `async def` to support the crawl4ai fallback tier.

## Task E — Prompt awareness + pipeline summarize step

### E1: Pipeline summarize step (`pipeline.py`)

After routing, before Step 2 (embedding), if `doc.content_type == "video"` and `raw_text` does not start with `[NO_TRANSCRIPT]`:

```python
yield "Summarizing transcript..."
raw_text = await asyncio.to_thread(summarize_transcript, raw_text, source)
```

This replaces `doc.raw_text` with a focused ~800-word summary before it reaches `enrich()`.

### E2: `summarize_transcript()` in `core/minimax_client.py`

New function alongside `enrich()`:

```python
def summarize_transcript(raw_text: str, source: str) -> str:
```

- Sends a focused prompt: "Summarize this video transcript in ~800 words. Preserve the speaker's core thesis, specific claims, concrete examples, and any data or frameworks introduced. Do not add commentary. Return plain text only."
- Truncates transcript to first 40,000 chars before sending (handles most videos up to ~3 hours)
- On failure: returns original `raw_text[:6000]` (graceful degradation)
- Returns plain string (not JSON)

### E3: Prompt adaptation in `enrich()` (`core/minimax_client.py`)

`_build_prompt()` gains `content_type: str` parameter. The instruction preamble at the top of `_NOTE_TEMPLATE` becomes content-type-specific:

| content_type | Instruction prefix added to prompt |
|---|---|
| `paper` | "Focus on methodology, findings, and limitations." |
| `article` | "Focus on the main argument and key evidence." |
| `tweet` | "Capture the exact argument and any specific claims or data points made." |
| `video` | "This is a transcript summary. Focus on the speaker's core thesis and concrete examples." |

`enrich()` signature: `enrich(raw_text, similar_titles, source, content_type="article") -> dict`

The JSON output schema is unchanged.

## File changes summary

| File | Change |
|---|---|
| `ingesters/__init__.py` | Add `Document` dataclass |
| `ingesters/tweet.py` | New — Nitter-based tweet extractor |
| `ingesters/news.py` | New — newspaper3k + crawl4ai + paywall fallback |
| `ingesters/youtube.py` | New — yt-dlp transcript extractor |
| `ingesters/web.py` | Unchanged (used as tier-2 fallback inside news.py) |
| `pipeline.py` | Add `_route()`, `content_type` threading, summarize step for video |
| `core/minimax_client.py` | Add `summarize_transcript()`, adapt `_build_prompt()` per content type |

## Dependencies to add

- `newspaper3k` — pip install
- `yt-dlp` — pip install (or system install; must be on PATH)

## Error handling

- Tweet: all Nitter instances fail → `ValueError` → pipeline yields error message, stops
- News: paywall → stub note written with `[PAYWALLED]` flag, no exception
- YouTube no subtitles → stub note written with `[NO_TRANSCRIPT]` flag, no exception
- YouTube transcript summarization fails → graceful degradation to truncated raw transcript
- All ingesters: unexpected exceptions bubble up to pipeline's existing `except Exception` handler

## Testing

Each ingester gets its own test file:
- `tests/test_tweet_ingester.py` — mock HTTP responses from Nitter, test instance rotation, test thread parsing, test malformed URL
- `tests/test_news_ingester.py` — mock newspaper3k success, mock newspaper3k failure + crawl4ai success, mock both fail (paywall path)
- `tests/test_youtube_ingester.py` — mock yt-dlp subprocess, test VTT stripping, test no-subtitle path
- `tests/test_router.py` — test URL pattern matching for all five route cases
- `tests/test_summarize_transcript.py` — mock MiniMax call, test fallback on API failure
