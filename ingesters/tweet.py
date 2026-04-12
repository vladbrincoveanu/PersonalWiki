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
