"""Tests for InterestDomainMatcher — checks if domain matches interest keywords."""
import pytest
from unittest.mock import patch


def test_is_interest_domain_returns_true_for_exact_match():
    """When domain keyword is in the keywords list, is_interest_domain returns True."""
    with patch("core.interest_domain_matcher.load_manual_keywords", return_value=["github.com", "arxiv.org"]):
        from core.interest_domain_matcher import InterestDomainMatcher
        matcher = InterestDomainMatcher()
        assert matcher.is_interest_domain("github.com") is True
        assert matcher.is_interest_domain("arxiv.org") is True


def test_is_interest_domain_returns_false_for_unknown():
    """When domain is not in keywords, returns False."""
    with patch("core.interest_domain_matcher.load_manual_keywords", return_value=["github.com"]):
        from core.interest_domain_matcher import InterestDomainMatcher
        matcher = InterestDomainMatcher()
        assert matcher.is_interest_domain("random-site.com") is False


def test_is_interest_domain_normalizes_www():
    """www variant should match non-www domain."""
    with patch("core.interest_domain_matcher.load_manual_keywords", return_value=["github.com"]):
        from core.interest_domain_matcher import InterestDomainMatcher
        matcher = InterestDomainMatcher()
        assert matcher.is_interest_domain("www.github.com") is True


def test_is_interest_domain_case_insensitive():
    """Domain matching should be case-insensitive."""
    with patch("core.interest_domain_matcher.load_manual_keywords", return_value=["GitHub.com"]):
        from core.interest_domain_matcher import InterestDomainMatcher
        matcher = InterestDomainMatcher()
        assert matcher.is_interest_domain("github.com") is True


def test_get_interest_domains_returns_all():
    """Returns all domains from keywords."""
    with patch("core.interest_domain_matcher.load_manual_keywords", return_value=["github.com", "arxiv.org", "pytorch.org"]):
        from core.interest_domain_matcher import InterestDomainMatcher
        matcher = InterestDomainMatcher()
        domains = matcher.get_interest_domains()
        assert domains == {"github.com", "arxiv.org", "pytorch.org"}


def test_get_interest_domains_excludes_non_domains():
    """Keywords that are not domains (e.g. 'distributed systems') are excluded."""
    with patch("core.interest_domain_matcher.load_manual_keywords", return_value=["github.com", "distributed systems", "RLHF"]):
        from core.interest_domain_matcher import InterestDomainMatcher
        matcher = InterestDomainMatcher()
        domains = matcher.get_interest_domains()
        assert "github.com" in domains
        assert "distributed systems" not in domains
        assert "RLHF" not in domains


def test_empty_interests_returns_empty_set():
    """No interests returns empty set."""
    with patch("core.interest_domain_matcher.load_manual_keywords", return_value=[]):
        from core.interest_domain_matcher import InterestDomainMatcher
        matcher = InterestDomainMatcher()
        assert matcher.get_interest_domains() == set()


def test_subdomain_matches_parent():
    """Subdomain of an interest domain should match."""
    with patch("core.interest_domain_matcher.load_manual_keywords", return_value=["github.com"]):
        from core.interest_domain_matcher import InterestDomainMatcher
        matcher = InterestDomainMatcher()
        assert matcher.is_interest_domain("api.github.com") is True
        assert matcher.is_interest_domain("gist.github.com") is True


def test_infers_domain_from_topic_keyword():
    """Topic keywords like 'PyTorch' infer domain pytorch.org."""
    with patch("core.interest_domain_matcher.load_manual_keywords", return_value=["PyTorch", "GitHub"]):
        from core.interest_domain_matcher import InterestDomainMatcher
        matcher = InterestDomainMatcher()
        assert matcher.is_interest_domain("pytorch.org") is True
        assert matcher.is_interest_domain("github.com") is True
