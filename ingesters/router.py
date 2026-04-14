import asyncio
import re
import urllib.request
from pathlib import Path
from ingesters import Document


_TWEET_RE = re.compile(r"https?://(?:twitter\.com|x\.com)/[^/]+/status/\d+")
_YOUTUBE_RE = re.compile(r"https?://(?:www\.)?youtube\.com/watch\?")
_ARXIV_RE = re.compile(r"https?://arxiv\.org/(?:abs|pdf)/\d+\.\d+")
_PDF_EXT_RE = re.compile(r"\.pdf(?:\?.*)?$", re.IGNORECASE)


def _is_pdf_url(url: str) -> bool:
    """Return True if the URL serves a PDF (by extension or Content-Type)."""
    if _PDF_EXT_RE.search(url.split("?")[0]):
        return True
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as resp:
            ct = resp.headers.get("Content-Type", "")
            return "application/pdf" in ct
    except Exception:
        return False


def route_url(url: str) -> str:
    """Return the ingester name to use for this URL: 'tweet', 'youtube', 'pdf', 'news', or 'web'."""
    if _TWEET_RE.match(url):
        return "tweet"
    if _YOUTUBE_RE.match(url):
        return "youtube"
    if _ARXIV_RE.match(url) or _is_pdf_url(url):
        return "pdf"
    return "news"


async def extract(url: str) -> Document:
    """Extract content from a URL, routing to the appropriate ingester."""
    ingester = route_url(url)

    if ingester == "tweet":
        from ingesters.tweet import extract_tweet
        return await asyncio.to_thread(extract_tweet, url)
    if ingester == "youtube":
        from ingesters.youtube import extract_youtube
        return await asyncio.to_thread(extract_youtube, url)
    if ingester == "pdf":
        # Download PDF to temp file and extract
        from ingesters.pdf import extract_pdf_full
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            await asyncio.to_thread(urllib.request.urlretrieve, url, tmp.name)
            result = await asyncio.to_thread(extract_pdf_full, tmp.name)
        return Document(
            raw_text=result.markdown,
            content_type="paper",
            images=result.images,
        )
    if ingester == "news":
        from ingesters.news import extract_news
        return await extract_news(url)
    # fallback to web crawler
    from ingesters.web import extract_url as extract_web
    text = await extract_web(url)
    return Document(raw_text=text, content_type="article")


def extract_pdf(pdf_path: str) -> Document:
    """Extract content from a local PDF file."""
    from ingesters.pdf import extract_pdf_full
    result = extract_pdf_full(pdf_path)
    return Document(
        raw_text=result.markdown,
        content_type="paper",
        images=result.images,
    )
