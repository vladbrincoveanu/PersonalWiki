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
    r'class="(?:p-text|tweet-content|timeline-message)[^"]*"[^>]*>(.*?)</(?:div|p)>',
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
            if resp.status != 200:
                return None
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
    syndication_text = None
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