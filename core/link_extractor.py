"""
LinkExtractor — regex-based HTML link extraction.

extract_links(html: str, base_url: str) -> list[str]
Finds all <a href="..."> tags in HTML, resolves relative URLs to absolute,
and returns deduplicated list in document order.
"""
import re
from urllib.parse import urljoin, urlparse


# Regex to match <a href="..."> — handles double quotes, single quotes, and no quotes
_HREF_RE = re.compile(
    r'''<a\s[^>]*href\s*=\s*
    (?:
        "([^"]*)"    |
        '([^']*)'    |
        ([^\s>]*)    # unquoted (no spaces or >)
    )''',
    re.IGNORECASE | re.VERBOSE | re.UNICODE,
)

# Schemes to skip (not follow)
_SKIP_SCHEMES = frozenset({"javascript", "mailto", "tel", "ftp", "file"})


def extract_links(html: str, base_url: str) -> list[str]:
    """
    Extract all outbound <a href> links from HTML and resolve to absolute URLs.

    Args:
        html: Raw HTML string to parse.
        base_url: Base URL used to resolve relative links.

    Returns:
        Deduplicated list of absolute URLs in document order.
        Skips javascript:, mailto:, and other non-http(s) schemes.
    """
    if not html:
        return []

    seen: set[str] = set()
    result: list[str] = []

    for match in _HREF_RE.finditer(html):
        # Get href from whichever group matched
        href = match.group(1) or match.group(2) or match.group(3) or ""
        href = href.strip()

        if not href:
            continue

        # Skip non-http schemes
        parsed_href = urlparse(href)
        scheme = parsed_href.scheme.lower()
        if scheme in _SKIP_SCHEMES:
            continue

        # Resolve relative to absolute
        full_url = urljoin(base_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        result.append(full_url)

    return result
