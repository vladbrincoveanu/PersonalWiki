# Tweet Enhanced Syndication + Nitter RSS Design

**Date:** 2026-04-13
**Status:** Draft

---

## Overview

Strengthen tweet extraction by adding: (1) more Nitter instances including `vxitter`, (2) Nitter RSS feed fallback, (3) per-tweet syndication URL, and (4) `publish.twitter.com` oEmbed endpoint.

---

## Problem

Current state after Task 2 fix:
- 8 Nitter instances — many are blocked or rate-limited
- `_fetch_via_syndication()` uses a timeline-profile URL that may not return specific tweet content
- No RSS feed fallback for Nitter
- `publish.twitter.com` oEmbed not tried

---

## Solution

### 1. More Nitter Instances

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
    # vxitter (most reliable current fork)
    "https://vxitter.nl",
    "https://nitter.1d4.us",
    "https://nitter.cat",
]
```

### 2. RSS Feed Fallback

Nitter exposes an RSS feed at `/{username}/status/{tweet_id}/rss`. This is more reliable than HTML parsing because RSS is structured:

```python
def _fetch_via_nitter_rss(username: str, tweet_id: str) -> str | None:
    """Try Nitter RSS feeds for all instances."""
    for instance in _NITTER_INSTANCES:
        try:
            url = f"{instance}/{username}/status/{tweet_id}/rss"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    return None
                content = resp.read().decode("utf-8", errors="replace")
                # Parse RSS <description> field
                import re
                desc_match = re.search(r"<description><!\[CDATA\[(.*?)\]\]></description>", content, re.DOTALL)
                if desc_match:
                    text = _strip_tags(desc_match.group(1))
                    if text.strip():
                        return text.strip()
                # Fallback: strip all tags
                return _strip_tags(content)
        except Exception:
            continue
    return None
```

### 3. Per-Tweet Syndication

The current `_fetch_via_syndication` uses timeline-profile. There's also a per-tweet syndication endpoint:

```python
def _fetch_via_syndication_tweet(username: str, tweet_id: str) -> str | None:
    """Try Twitter's per-tweet syndication endpoint."""
    url = f"https://syndication.twitter.com/srv/timeline-detail/screen-name/{username}?tweet_id={tweet_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return None
            content = resp.read().decode("utf-8", errors="replace")
            bodies = _TWEET_BODY_RE.findall(content)
            if bodies:
                return " ".join(_strip_tags(b) for b in bodies[:5] if _strip_tags(b))
            return _strip_tags(content)
    except Exception:
        return None
```

### 4. publish.twitter.com oEmbed

`publish.twitter.com` converts a tweet URL to oEmbed format:

```python
def _fetch_via_publish_twitter(username: str, tweet_id: str) -> str | None:
    """Try Twitter's publish oEmbed endpoint."""
    tweet_url = f"https://twitter.com/{username}/status/{tweet_id}"
    url = f"https://publish.twitter.com/oembed?url={urllib.parse.quote(tweet_url)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                return None
            import json
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return _strip_tags(data.get("html", ""))
    except Exception:
        return None
```

### Updated Extraction Order

```
extract_tweet(url):
  1. Try all 11 Nitter HTML instances
  2. Try Nitter RSS feeds (all instances)
  3. Try publish.twitter.com oEmbed
  4. Try per-tweet syndication endpoint
  5. Return [NO_TWEET] stub
```

---

## Testing

| Test | Description |
|------|-------------|
| `test_tweet_nitter_rss_fallback` | All HTML instances fail, RSS returns content |
| `test_tweet_publish_twitter_oembed` | oEmbed returns tweet text |
| `test_tweet_per_tweet_syndication` | Per-tweet syndication URL returns content |

---

## Out of Scope

- Twitter API v2 authentication
- Rate limit handling beyond instance rotation
- Tweet engagement metrics
