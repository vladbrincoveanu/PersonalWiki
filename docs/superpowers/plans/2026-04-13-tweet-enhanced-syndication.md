# Tweet Enhanced Syndication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 3 more Nitter instances (vxitter, nitter.1d4.us, nitter.cat), Nitter RSS feed fallback, and publish.twitter.com oEmbed fallback to maximize tweet extraction reliability.

**Architecture:** `extract_tweet` gains two new fallback methods: `_fetch_via_nitter_rss()` (tries RSS feeds across all Nitter instances) and `_fetch_via_publish_twitter()` (tries Twitter's oEmbed endpoint). Extraction order becomes: Nitter HTML → Nitter RSS → publish.twitter.com → per-tweet syndication → stub.

**Tech Stack:** stdlib `urllib`, `re`, `json`; no new dependencies.

---

## File Map

| File | Change |
|------|--------|
| `ingesters/tweet.py` | Add 3 Nitter instances, add `_fetch_via_nitter_rss`, add `_fetch_via_publish_twitter`, update `extract_tweet` call order |
| `tests/test_tweet_ingester.py` | Add RSS fallback, oEmbed fallback, and per-tweet syndication tests |

---

## Task 1: Add Nitter Instances and RSS Fallback

**Files:**
- Modify: `ingesters/tweet.py` — add `_fetch_via_nitter_rss` and 3 instances
- Test: `tests/test_tweet_ingester.py` — add RSS fallback test

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tweet_ingester.py — add this test

def test_tweet_nitter_rss_fallback(monkeypatch):
    """All Nitter HTML instances fail, RSS feed returns content."""
    import ingesters.tweet as tw

    rss_calls = []
    def mock_urlopen(url, timeout=10):
        url_str = url.get_full_url() if hasattr(url, 'get_full_url') else str(url)
        if "/rss" in url_str or "/feed" in url_str:
            rss_calls.append(url_str)
            # RSS XML with CDATA description
            xml = '''<?xml version="1.0"?>
<rss><channel><item>
<description><![CDATA[Hello from RSS tweet content]]></description>
</item></channel></rss>'''
            from unittest.mock import MagicMock
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.status = 200
            m.read.return_value = xml.encode()
            return m
        raise Exception("HTML instance failed")

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    doc = tw.extract_tweet("https://twitter.com/user/status/123")
    assert "RSS tweet content" in doc.raw_text
    assert doc.content_type == "tweet"
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_tweet_ingester.py -k "rss" -v
```

- [ ] **Step 3: Add instances and RSS fallback**

In `ingesters/tweet.py`:

**Replace `_NITTER_INSTANCES` with (add 3 new instances):**

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
    # vxitter and other reliable forks
    "https://vxitter.nl",
    "https://nitter.1d4.us",
    "https://nitter.cat",
]
```

**Add `_fetch_via_nitter_rss` function after `_fetch_via_syndication`:**

```python
def _fetch_via_nitter_rss(username: str, tweet_id: str) -> str | None:
    """Try Nitter RSS feeds across all instances."""
    for instance in _NITTER_INSTANCES:
        try:
            url = f"{instance}/{username}/status/{tweet_id}/rss"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    continue
                content = resp.read().decode("utf-8", errors="replace")
                # Extract <description> from RSS item (may be in CDATA)
                desc_match = re.search(
                    r"<description><!\[CDATA\[(.*?)\]\]></description>",
                    content, re.DOTALL
                )
                if desc_match:
                    text = _strip_tags(desc_match.group(1))
                    if text.strip():
                        return text.strip()
                # Fallback: strip all tags from content
                text = _strip_tags(content)
                if text.strip():
                    return text.strip()
        except Exception:
            continue
    return None
```

- [ ] **Step 4: Update `extract_tweet` to call RSS after HTML**

Find the section in `extract_tweet` after the Nitter HTML loop, before `_fetch_via_syndication`. Insert the RSS call:

```python
    # Try Nitter RSS feeds if HTML failed
    if html is None:
        rss_text = _fetch_via_nitter_rss(username, tweet_id)
        if rss_text and rss_text.strip():
            return Document(raw_text=rss_text.strip(), content_type="tweet")

    # Try syndication if RSS failed
    syndication_text = None
    if html is None:
        syndication_text = _fetch_via_syndication(username, tweet_id)
        if syndication_text and syndication_text.strip():
            return Document(raw_text=syndication_text.strip(), content_type="tweet")
```

- [ ] **Step 5: Run RSS test — verify it passes**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_tweet_ingester.py -k "rss" -v
```

- [ ] **Step 6: Commit**

```bash
git add ingesters/tweet.py tests/test_tweet_ingester.py
git commit -m "feat(tweet): add Nitter RSS feed fallback and 3 more instances"
```

---

## Task 2: Add publish.twitter.com oEmbed Fallback

**Files:**
- Modify: `ingesters/tweet.py` — add `_fetch_via_publish_twitter`
- Test: `tests/test_tweet_ingester.py` — add oEmbed test

- [ ] **Step 1: Write failing test**

```python
# tests/test_tweet_ingester.py — add this test

def test_tweet_publish_twitter_oembed(monkeypatch):
    """publish.twitter.com oEmbed returns tweet text."""
    import ingesters.tweet as tw

    oembed_calls = []
    def mock_urlopen(url, timeout=10):
        url_str = url.get_full_url() if hasattr(url, 'get_full_url') else str(url)
        if "publish.twitter.com" in url_str:
            oembed_calls.append(url_str)
            import json
            response = json.dumps({
                "html": "<blockquote><p>Hello from oEmbed</p></blockquote>",
                "text": "Hello from oEmbed"
            })
            from unittest.mock import MagicMock
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.status = 200
            m.read.return_value = response.encode()
            return m
        raise Exception("all other sources failed")

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    doc = tw.extract_tweet("https://twitter.com/user/status/123")
    assert "Hello from oEmbed" in doc.raw_text
    assert doc.content_type == "tweet"
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_tweet_ingester.py -k "oembed" -v
```

- [ ] **Step 3: Add `_fetch_via_publish_twitter`**

Add after `_fetch_via_nitter_rss`:

```python
def _fetch_via_publish_twitter(username: str, tweet_id: str) -> str | None:
    """Use Twitter's publish.twitter.com oEmbed endpoint."""
    tweet_url = f"https://twitter.com/{username}/status/{tweet_id}"
    url = f"https://publish.twitter.com/oembed?url={urllib.parse.quote(tweet_url)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return None
            import json
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            # Prefer html field, strip blockquote tags
            html = data.get("html", "")
            if html:
                return _strip_tags(html)
            return _strip_tags(data.get("text", ""))
    except Exception:
        return None
```

**Add `import urllib.parse` at top of file if not present.**

- [ ] **Step 4: Update `extract_tweet` to call oEmbed after syndication**

In `extract_tweet`, after the syndication call, before the stub:

```python
    # Try publish.twitter.com oEmbed if syndication failed
    if html is None:
        oembed_text = _fetch_via_publish_twitter(username, tweet_id)
        if oembed_text and oembed_text.strip():
            return Document(raw_text=oembed_text.strip(), content_type="tweet")
```

- [ ] **Step 5: Run oEmbed test — verify it passes**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate && pytest tests/test_tweet_ingester.py -k "oembed" -v
```

- [ ] **Step 6: Commit**

```bash
git add ingesters/tweet.py tests/test_tweet_ingester.py
git commit -m "feat(tweet): add publish.twitter.com oEmbed fallback"
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
| 3 more Nitter instances (vxitter, nitter.1d4.us, nitter.cat) | Task 1 |
| Nitter RSS feed fallback | Task 1 |
| publish.twitter.com oEmbed fallback | Task 2 |
| All tests pass | Task 3 |
