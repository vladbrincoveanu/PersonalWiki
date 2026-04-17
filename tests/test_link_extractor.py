"""Tests for LinkExtractor — regex-based HTML link extraction."""
import pytest
from core.link_extractor import extract_links


def test_extract_links_finds_absolute_links():
    html = '<a href="https://example.com/article">Article</a>'
    links = extract_links(html, "https://base.com")
    assert "https://example.com/article" in links


def test_extract_links_resolves_relative_urls():
    html = '<a href="/blog/my-post">Post</a>'
    links = extract_links(html, "https://example.com")
    assert "https://example.com/blog/my-post" in links


def test_extract_links_resolves_parent_relative():
    html = '<a href="../article">Article</a>'
    links = extract_links(html, "https://example.com/subfolder/page")
    assert "https://example.com/article" in links


def test_extract_links_resolves_root_relative():
    html = '<a href="/article">Article</a>'
    links = extract_links(html, "https://example.com/subfolder/")
    assert "https://example.com/article" in links


def test_extract_links_handles_query_params():
    html = '<a href="/article?id=123&tag=python">Article</a>'
    links = extract_links(html, "https://example.com")
    assert "https://example.com/article?id=123&tag=python" in links


def test_extract_links_handles_fragment():
    html = '<a href="/article#section">Article</a>'
    links = extract_links(html, "https://example.com")
    assert "https://example.com/article#section" in links


def test_extract_links_handles_no_href():
    html = '<a>No href</a>'
    links = extract_links(html, "https://example.com")
    assert links == []


def test_extract_links_skips_javascript():
    html = '<a href="javascript:void(0)">JS link</a>'
    links = extract_links(html, "https://example.com")
    assert "javascript:void(0)" not in links


def test_extract_links_skips_mailtos():
    html = '<a href="mailto:test@example.com">Email</a>'
    links = extract_links(html, "https://example.com")
    assert "mailto:test@example.com" not in links


def test_extract_links_preserves_order():
    html = """
    <a href="/link1">1</a>
    <a href="/link2">2</a>
    <a href="/link3">3</a>
    """
    links = extract_links(html, "https://example.com")
    assert links == [
        "https://example.com/link1",
        "https://example.com/link2",
        "https://example.com/link3",
    ]


def test_extract_links_handles_double_quotes():
    html = '<a href="/page">Page</a>'
    links = extract_links(html, "https://example.com")
    assert len(links) == 1


def test_extract_links_handles_single_quotes():
    html = "<a href='/page'>Page</a>"
    links = extract_links(html, "https://example.com")
    assert len(links) == 1


def test_extract_links_handles_ang_brackets():
    html = '<a href=/page>No quotes</a>'
    links = extract_links(html, "https://example.com")
    assert len(links) == 1


def test_extract_links_empty_html():
    links = extract_links("", "https://example.com")
    assert links == []


def test_extract_links_no_anchor_tags():
    html = "<p>No links here</p>"
    links = extract_links(html, "https://example.com")
    assert links == []


def test_extract_links_normalizes_protocol_relative():
    html = '<a href="//cdn.example.com/assets">CDN</a>'
    links = extract_links(html, "https://example.com")
    assert "https://cdn.example.com/assets" in links


def test_extract_links_handles_duplicate_hrefs():
    html = '<a href="/page">1</a><a href="/page">2</a>'
    links = extract_links(html, "https://example.com")
    assert links.count("https://example.com/page") == 1
