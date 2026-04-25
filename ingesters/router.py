import asyncio
import re
import urllib.request
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
        import os
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
            await asyncio.to_thread(urllib.request.urlretrieve, url, tmp_path)
            # Validate magic bytes before passing to docling
            with open(tmp_path, "rb") as f:
                header = f.read(5)
            if header != b"%PDF-":
                raise ValueError(
                    f"URL has .pdf extension but content is not valid PDF "
                    f"(got header: {header!r}). Treating as web page instead."
                )
            result = await asyncio.to_thread(extract_pdf_full, tmp_path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
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


def extract_docx(docx_path: str) -> Document:
    from ingesters.docx import extract_docx as _extract
    return _extract(docx_path)


def extract_markdown(md_path: str) -> Document:
    from ingesters.markdown import extract_markdown as _extract
    return _extract(md_path)
