"""
SitemapDiscovery — fetch and filter sitemap entries by keyword.

Uses crawl4ai's AsyncWebCrawler to probe a domain for sitemap XML files,
then parses and filters entries.
"""

import re
from typing import Optional

try:
    from crawl4ai import AsyncWebCrawler
except ImportError:
    AsyncWebCrawler = None  # type: ignore

_SITEMAP_PATHS = ["sitemap.xml", "sitemap-index.xml", "sitemap1.xml", "sitemap_news.xml", "sitemap_images.xml"]


def _build_sitemap_urls(domain: str) -> list[str]:
    """
    Build a list of candidate sitemap URLs for a domain.

    Includes:
    - Same-domain variants: /sitemap.xml, /sitemap-index.xml
    - Parent-domain variants when domain has a subdomain
    - Common variant names: sitemap1.xml, sitemap_news.xml, sitemap_images.xml
    """
    base = domain.lstrip("https://").lstrip("www.")
    parts = base.split(".", 1)
    subdomain = parts[0] if len(parts) > 1 else None
    parent_domain = parts[1] if len(parts) > 1 else base

    urls = []

    # Subdomain variants
    if subdomain:
        for path in _SITEMAP_PATHS:
            urls.append(f"https://{domain}/{path}")
            urls.append(f"https://{subdomain}.{parent_domain}/{path}")

    # Parent domain variants
    for path in _SITEMAP_PATHS:
        urls.append(f"https://{parent_domain}/{path}")

    return urls


def _filter_by_keyword(entries: list[dict], keyword: str) -> list[dict]:
    """
    Keep only entries whose URL contains the keyword (case-insensitive).
    """
    kw_lower = keyword.lower()
    return [e for e in entries if kw_lower in e.get("url", "").lower()]


def _parse_sitemap_xml(content: str) -> list[dict]:
    """
    Parse sitemap XML content.

    Handles both regular <urlset> and sitemap-index <sitemapindex> formats.
    Returns a list of dicts with keys: url, lastmod, priority (None if absent).
    """
    entries = []

    # Match <loc>...</loc> blocks
    loc_pattern = re.compile(r"<loc>([^<]+)</loc>", re.IGNORECASE)
    lastmod_pattern = re.compile(r"<lastmod>([^<]+)</lastmod>", re.IGNORECASE)
    priority_pattern = re.compile(r"<priority>([^<]+)</priority>", re.IGNORECASE)

    # Find all <url> or <sitemap> blocks
    block_pattern = re.compile(
        r"<(?:url|sitemap)>(.*?)</(?:url|sitemap)>",
        re.IGNORECASE | re.DOTALL,
    )

    for block in block_pattern.finditer(content):
        block_text = block.group(1)

        loc_match = loc_pattern.search(block_text)
        if not loc_match:
            continue

        url = loc_match.group(1).strip()

        lastmod_match = lastmod_pattern.search(block_text)
        lastmod = lastmod_match.group(1).strip() if lastmod_match else ""

        priority_match = priority_pattern.search(block_text)
        priority = priority_match.group(1).strip() if priority_match else ""

        entries.append({
            "url": url,
            "lastmod": lastmod if lastmod else None,
            "priority": priority if priority else None,
        })

    return entries


def _is_sitemapindex_entry(entry: dict) -> bool:
    """Entries from a sitemap-index have no lastmod and no priority."""
    return entry.get("lastmod") is None and entry.get("priority") is None


async def _fetch_one_sitemap(sitemap_url: str) -> list[dict]:
    """
    Fetch and parse a single sitemap URL (urlset only).
    Returns list of entries with url/lastmod/priority.
    """
    try:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.araw_get(sitemap_url)
            if result is None or not getattr(result, "success", True):
                return []
            xml_content: str = getattr(result, "markdown", "") or ""
            if not xml_content.strip():
                return []
            return _parse_sitemap_xml(xml_content)
    except Exception:
        return []


async def fetch_sitemap(domain: str, keyword: str) -> list[dict]:
    """
    Fetch and filter sitemap entries for a domain.

    Probes multiple sitemap URLs via crawl4ai AsyncWebCrawler,
    parses the first successful response. If the response is a sitemap-index,
    recursively fetches each child sitemap and collects their URL entries.
    Finally filters by keyword and returns entries as list of {url, lastmod, priority}.

    Returns an empty list if no sitemap is found or no entries match the keyword.
    """
    sitemap_urls = _build_sitemap_urls(domain)

    for sitemap_url in sitemap_urls:
        try:
            entries = await _fetch_one_sitemap(sitemap_url)
            if not entries:
                continue

            # Detect sitemap-index: entries have no lastmod and no priority
            if _is_sitemapindex_entry(entries[0]):
                # Recursively fetch each child sitemap and collect entries
                all_entries = []
                for entry in entries:
                    child_entries = await _fetch_one_sitemap(entry["url"])
                    all_entries.extend(child_entries)
                entries = all_entries

            filtered = _filter_by_keyword(entries, keyword)
            if filtered:
                return filtered
        except Exception:
            # If this URL fails, try the next one
            continue

    return []
