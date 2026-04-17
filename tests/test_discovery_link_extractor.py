"""Tests for DiscoveryLinkExtractor — process page links and enqueue interest domains."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


def test_process_page_links_extracts_and_filters():
    """Links are extracted and filtered by interest domain."""
    html = """
    <html><body>
        <a href="https://github.com/user/project">GitHub project</a>
        <a href="https://random-site.com/page">Random</a>
        <a href="https://pytorch.org/tutorials">PyTorch tutorial</a>
    </body></html>
    """
    with patch("core.interest_domain_matcher.extract_interests", return_value=["github.com", "pytorch.org"]):
        from core.interest_domain_matcher import InterestDomainMatcher
        from core.discovery_link_extractor import DiscoveryLinkExtractor

        mock_scheduler = MagicMock()
        mock_scheduler._is_new_url.return_value = True
        mock_scheduler._interest_domains = set()

        extractor = DiscoveryLinkExtractor(matcher=InterestDomainMatcher())
        extractor.process_page_links("https://example.com/article", html, mock_scheduler)

        # Should have queued github.com and pytorch.org
        assert mock_scheduler._enqueue_interest_domain.call_count >= 1


def test_process_page_links_skips_non_interest_domains():
    """Links to non-interest domains are skipped."""
    html = '<html><body><a href="https://random-site.com/page">Random</a></body></html>'
    with patch("core.interest_domain_matcher.extract_interests", return_value=["github.com"]):
        from core.interest_domain_matcher import InterestDomainMatcher
        from core.discovery_link_extractor import DiscoveryLinkExtractor

        mock_scheduler = MagicMock()
        extractor = DiscoveryLinkExtractor(matcher=InterestDomainMatcher())
        extractor.process_page_links("https://example.com/article", html, mock_scheduler)

        # No domains enqueued
        mock_scheduler._enqueue_interest_domain.assert_not_called()


def test_process_page_links_handles_empty_html():
    """Empty HTML produces no links."""
    from core.discovery_link_extractor import DiscoveryLinkExtractor
    from core.interest_domain_matcher import InterestDomainMatcher

    mock_scheduler = MagicMock()
    extractor = DiscoveryLinkExtractor(matcher=InterestDomainMatcher())
    extractor.process_page_links("https://example.com/article", "", mock_scheduler)
    mock_scheduler._enqueue_interest_domain.assert_not_called()
