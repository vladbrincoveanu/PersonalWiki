import asyncio
import ipaddress
import shutil
import socket
import urllib.request
from urllib.parse import parse_qs, urlsplit, urlunsplit
from ingesters import Document


_TWEET_HOSTS = {"twitter.com", "www.twitter.com", "x.com", "www.x.com"}
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com"}
_ARXIV_HOST = "arxiv.org"
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}


def _is_public_hostname(hostname: str) -> bool:
    """Return whether a hostname resolves only to publicly routable addresses."""
    normalized = hostname.rstrip(".").lower()
    if normalized in _BLOCKED_HOSTNAMES or normalized.endswith((".local", ".internal")):
        return False

    try:
        addresses = {ipaddress.ip_address(normalized)}
    except ValueError:
        try:
            infos = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
        except OSError:
            return False
        addresses = {ipaddress.ip_address(info[4][0]) for info in infos}

    return bool(addresses) and all(
        not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        )
        for address in addresses
    )


def _validate_external_url(url: str) -> str:
    """Validate a user-supplied URL before any network request is made.

    Ingestion is intentionally limited to public HTTP(S) endpoints.  This
    prevents requests to loopback, link-local cloud metadata, private, and
    reserved networks while retaining ordinary web/PDF ingestion.
    """
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL must use http or https and include a host")
    if parsed.username or parsed.password:
        raise ValueError("URL credentials are not allowed")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("URL contains an invalid port") from exc
    if not _is_public_hostname(parsed.hostname):
        raise ValueError("URL host must resolve to a public address")
    return urlunsplit(parsed)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects that leave the validated public network boundary."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_external_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_pdf(url: str, destination: str) -> None:
    """Download a PDF while validating the initial URL and every redirect."""
    safe_url = _validate_external_url(url)
    opener = urllib.request.build_opener(_SafeRedirectHandler)
    request = urllib.request.Request(safe_url, headers={"User-Agent": "personalWiki/1.0"})
    with opener.open(request, timeout=30) as response, open(destination, "wb") as output:
        shutil.copyfileobj(response, output)


def _has_numeric_arxiv_id(path: str) -> bool:
    parts = path.strip("/").split("/")
    if len(parts) != 2 or parts[0] not in {"abs", "pdf"}:
        return False
    identifier = parts[1]
    dot = identifier.find(".")
    return (
        dot > 0
        and dot < len(identifier) - 1
        and identifier[:dot].isdigit()
        and identifier[dot + 1 :].isdigit()
    )


def _is_tweet_url(parsed) -> bool:
    parts = [part for part in parsed.path.split("/") if part]
    return (
        parsed.hostname in _TWEET_HOSTS
        and len(parts) == 3
        and parts[1] == "status"
        and parts[2].isdigit()
    )


def _is_youtube_url(parsed) -> bool:
    query = parse_qs(parsed.query)
    return (
        parsed.hostname in _YOUTUBE_HOSTS
        and parsed.path.rstrip("/") == "/watch"
        and bool(query.get("v"))
    )


def _is_pdf_url(url: str) -> bool:
    """Return True when the URL path explicitly identifies a PDF.

    Do not probe arbitrary user URLs during routing.  Besides adding latency,
    a HEAD request here turns route classification into an SSRF primitive.
    """
    return urlsplit(url).path.lower().endswith(".pdf")


def route_url(url: str) -> str:
    """Return the ingester name to use for this URL: 'tweet', 'youtube', 'pdf', 'news', or 'web'."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must use http or https and include a host")
    if _is_tweet_url(parsed):
        return "tweet"
    if _is_youtube_url(parsed):
        return "youtube"
    if parsed.hostname == _ARXIV_HOST and _has_numeric_arxiv_id(parsed.path):
        return "pdf"
    if _is_pdf_url(url):
        return "pdf"
    return "news"


async def extract(url: str) -> Document:
    """Extract content from a URL, routing to the appropriate ingester."""
    safe_url = _validate_external_url(url)
    ingester = route_url(safe_url)

    if ingester == "tweet":
        from ingesters.tweet import extract_tweet
        return await asyncio.to_thread(extract_tweet, safe_url)
    if ingester == "youtube":
        from ingesters.youtube import extract_youtube
        return await asyncio.to_thread(extract_youtube, safe_url)
    if ingester == "pdf":
        # Download PDF to temp file and extract
        from ingesters.pdf import extract_pdf_full
        import tempfile
        import os
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
            await asyncio.to_thread(_download_pdf, safe_url, tmp_path)
            # Validate magic bytes before passing to the PDF extractor.
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
        return await extract_news(safe_url)
    # fallback to web crawler
    from ingesters.web import extract_url as extract_web
    text = await extract_web(safe_url)
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
