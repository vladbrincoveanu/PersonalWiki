import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _build_mock_result(xml_content: str):
    mock = MagicMock()
    mock.success = True
    mock.markdown = xml_content
    return mock


# -------------------------------------------------------------------
# Tests for _build_sitemap_urls
# -------------------------------------------------------------------

def test_build_sitemap_urls_exact():
    from core.sitemap_discovery import _build_sitemap_urls
    urls = _build_sitemap_urls("example.com")
    assert "https://example.com/sitemap.xml" in urls
    assert "https://example.com/sitemap-index.xml" in urls


def test_build_sitemap_urls_variants():
    from core.sitemap_discovery import _build_sitemap_urls
    urls = _build_sitemap_urls("blog.example.com")
    # Should include blog subdomain variants
    assert "https://blog.example.com/sitemap.xml" in urls
    assert "https://blog.example.com/sitemap-index.xml" in urls
    # Also parent domain variants
    assert "https://example.com/sitemap.xml" in urls
    # Should include variant names
    variant_names = ["sitemap1.xml", "sitemap_news.xml", "sitemap_images.xml"]
    for name in variant_names:
        assert any(name in u for u in urls), f"Missing variant {name}"


# -------------------------------------------------------------------
# Tests for _filter_by_keyword
# -------------------------------------------------------------------

def test_keyword_filter():
    from core.sitemap_discovery import _filter_by_keyword
    entries = [
        {"url": "https://example.com/transformer-paper", "lastmod": "2024-01-01", "priority": "0.8"},
        {"url": "https://example.com/attention-is-all-you-need", "lastmod": "2024-01-02", "priority": "0.9"},
        {"url": "https://example.com/cat-pictures", "lastmod": "2024-01-03", "priority": "0.7"},
    ]
    result = _filter_by_keyword(entries, "transformer")
    assert len(result) == 1
    assert result[0]["url"] == "https://example.com/transformer-paper"


def test_keyword_filter_case_insensitive():
    from core.sitemap_discovery import _filter_by_keyword
    entries = [
        {"url": "https://example.com/TRANSFORMER-paper", "lastmod": "2024-01-01", "priority": "0.8"},
        {"url": "https://example.com/attention-is-all-you-need", "lastmod": "2024-01-02", "priority": "0.9"},
    ]
    result = _filter_by_keyword(entries, "transformer")
    assert len(result) == 1


def test_keyword_filter_no_match():
    from core.sitemap_discovery import _filter_by_keyword
    entries = [
        {"url": "https://example.com/transformer-paper", "lastmod": "2024-01-01", "priority": "0.8"},
    ]
    result = _filter_by_keyword(entries, "nonexistent")
    assert len(result) == 0


# -------------------------------------------------------------------
# Tests for _parse_sitemap_xml
# -------------------------------------------------------------------

def test_parse_sitemap_xml_urlset():
    from core.sitemap_discovery import _parse_sitemap_xml
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/page1</loc>
    <lastmod>2024-01-01</lastmod>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://example.com/page2</loc>
    <lastmod>2024-01-02</lastmod>
    <priority>0.6</priority>
  </url>
</urlset>'''
    result = _parse_sitemap_xml(xml)
    assert len(result) == 2
    assert result[0]["url"] == "https://example.com/page1"
    assert result[0]["lastmod"] == "2024-01-01"
    assert result[0]["priority"] == "0.8"


def test_parse_sitemap_xml_sitemapindex():
    from core.sitemap_discovery import _parse_sitemap_xml
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>https://example.com/sitemap1.xml</loc>
    <lastmod>2024-01-01</lastmod>
  </sitemap>
  <sitemap>
    <loc>https://example.com/sitemap2.xml</loc>
    <lastmod>2024-01-02</lastmod>
  </sitemap>
</sitemapindex>'''
    result = _parse_sitemap_xml(xml)
    assert len(result) == 2
    assert result[0]["url"] == "https://example.com/sitemap1.xml"
    assert result[0]["lastmod"] == "2024-01-01"


def test_parse_sitemap_xml_missing_priority():
    from core.sitemap_discovery import _parse_sitemap_xml
    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/page1</loc>
    <lastmod>2024-01-01</lastmod>
  </url>
</urlset>'''
    result = _parse_sitemap_xml(xml)
    assert len(result) == 1
    assert result[0]["url"] == "https://example.com/page1"
    assert result[0]["priority"] is None


# -------------------------------------------------------------------
# Tests for fetch_sitemap
# -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_sitemap_success():
    from core.sitemap_discovery import fetch_sitemap

    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/transformer-paper</loc>
    <lastmod>2024-01-01</lastmod>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://example.com/cat-pictures</loc>
    <lastmod>2024-01-02</lastmod>
    <priority>0.7</priority>
  </url>
</urlset>'''

    mock_result = _build_mock_result(xml)

    class MockCrawler:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        araw_get = AsyncMock(return_value=mock_result)

    with patch("core.sitemap_discovery.AsyncWebCrawler", return_value=MockCrawler()):
        result = await fetch_sitemap("example.com", "transformer")

    assert len(result) == 1
    assert result[0]["url"] == "https://example.com/transformer-paper"


@pytest.mark.asyncio
async def test_fetch_sitemap_no_sitemap_found():
    from core.sitemap_discovery import fetch_sitemap

    mock_result = MagicMock()
    mock_result.success = False
    mock_result.markdown = ""

    class MockCrawler:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        araw_get = AsyncMock(return_value=mock_result)

    with patch("core.sitemap_discovery.AsyncWebCrawler", return_value=MockCrawler()):
        result = await fetch_sitemap("example.com", "transformer")

    assert result == []


@pytest.mark.asyncio
async def test_fetch_sitemap_no_keyword_matches():
    from core.sitemap_discovery import fetch_sitemap

    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/cat-pictures</loc>
    <lastmod>2024-01-01</lastmod>
    <priority>0.7</priority>
  </url>
</urlset>'''

    mock_result = _build_mock_result(xml)

    class MockCrawler:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        araw_get = AsyncMock(return_value=mock_result)

    with patch("core.sitemap_discovery.AsyncWebCrawler", return_value=MockCrawler()):
        result = await fetch_sitemap("example.com", "transformer")

    assert result == []


@pytest.mark.asyncio
async def test_fetch_sitemap_resolves_sitemapindex():
    """When a sitemap-index is returned, child sitemaps are fetched and their URLs returned."""
    from core.sitemap_discovery import fetch_sitemap

    # First call returns sitemapindex (entries with no lastmod and no priority)
    sitemapindex_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>https://example.com/sitemap1.xml</loc>
  </sitemap>
</sitemapindex>'''

    # Second call returns urlset with matching URL
    urlset_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/transformer-paper</loc>
    <lastmod>2024-01-01</lastmod>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://example.com/cat-pictures</loc>
    <lastmod>2024-01-02</lastmod>
    <priority>0.7</priority>
  </url>
</urlset>'''

    call_log = []

    class MockCrawler:
        async def __a__(self): return self
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def araw_get(self, url):
            call_log.append(url)
            if "sitemap1" in url:
                return _build_mock_result(urlset_xml)
            return _build_mock_result(sitemapindex_xml)

    with patch("core.sitemap_discovery.AsyncWebCrawler", return_value=MockCrawler()):
        result = await fetch_sitemap("example.com", "transformer")

    assert len(result) == 1
    assert result[0]["url"] == "https://example.com/transformer-paper"
    # Verify child sitemap was actually fetched
    assert "https://example.com/sitemap1.xml" in call_log
