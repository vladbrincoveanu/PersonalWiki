import re
from urllib.parse import urljoin, urlparse
from core.site_registry import SiteRegistry

_registry: SiteRegistry | None = None


def _get_registry() -> SiteRegistry:
    global _registry
    if _registry is None:
        _registry = SiteRegistry()
    return _registry


def _get_domain(url: str) -> str:
    return urlparse(url).netloc


def extract_links(page_url: str, html: str) -> list[tuple[str, str]]:
    """Extract outbound links from HTML, filter by known domain.

    Returns list of (source_page_url, target_url) tuples for links
    whose target domain is already in the SiteRegistry.
    """
    reg = _get_registry()
    link_re = re.compile(r'href="([^"#>]+)"')
    results = []

    for match in link_re.finditer(html):
        href = match.group(1)
        if not href.startswith("http"):
            continue

        full_url = urljoin(page_url, href)
        target_domain = _get_domain(full_url)
        if reg.is_known(target_domain):
            results.append((page_url, full_url))

    return results