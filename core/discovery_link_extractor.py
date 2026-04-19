"""
DiscoveryLinkExtractor — extract links from crawled pages and route interest-domain links.

process_page_links(url: str, html: str, scheduler: DiscoveryScheduler)
    Extract all outbound links from HTML, filter by InterestDomainMatcher,
    and enqueue new interest domains for sitemap discovery.
"""
import logging
from urllib.parse import urlparse

from core.link_extractor import extract_links
from core.interest_domain_matcher import InterestDomainMatcher

_logger = logging.getLogger(__name__)


class DiscoveryLinkExtractor:
    """
    Extract outbound links from crawled pages and enqueue interest-domain links.

    Used after every page crawl (article, category, sitemap) to discover
    new interest domains and expand the discovery graph.
    """

    def __init__(self, matcher: InterestDomainMatcher | None = None):
        self._matcher = matcher or InterestDomainMatcher()

    def process_page_links(self, page_url: str, html: str, scheduler) -> None:
        """
        Extract links from page HTML and enqueue new interest domains.

        Args:
            page_url: URL of the page (used as base for relative links).
            html: Raw HTML content of the page.
            scheduler: DiscoveryScheduler instance with _enqueue_interest_domain method.
        """
        if not html:
            return

        links = extract_links(html, page_url)

        for link in links:
            domain = self._extract_domain(link)
            if not domain:
                continue
            if self._matcher.is_interest_domain(domain):
                if not scheduler.is_interest_domain_enqueued(domain):
                    try:
                        scheduler._enqueue_interest_domain(domain)
                    except Exception as e:
                        _logger.debug("Discovery: failed to enqueue interest domain %s: %s", domain, e)

    def _extract_domain(self, url: str) -> str:
        """Extract clean domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return ""
