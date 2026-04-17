from unittest.mock import MagicMock, patch
from core.sitemap_link_extractor import extract_links


def test_extract_links_filters_by_known_domain():
    with patch("core.sitemap_link_extractor._get_registry") as mock_get_reg:
        mock_reg = MagicMock()
        mock_reg.is_known.side_effect = lambda d: d == "known.com"
        mock_get_reg.return_value = mock_reg

        html = '''
        <a href="https://known.com/article">Known</a>
        <a href="https://unknown.com/article">Unknown</a>
        <a href="https://also-known.com/page">Also Known</a>
        '''
        result = extract_links("https://source.com/page", html)
        urls = [target for _, target in result]
        assert "https://known.com/article" in urls
        assert "https://also-known.com/page" in urls
        assert "https://unknown.com/article" not in urls


def test_extract_links_preserves_source():
    with patch("core.sitemap_link_extractor._get_registry") as mock_get_reg:
        mock_reg = MagicMock()
        mock_reg.is_known.return_value = True
        mock_get_reg.return_value = mock_reg

        html = '<a href="https://example.com/p1"><a href="https://example.com/p2">'
        result = extract_links("https://source.com/article", html)
        sources = [src for src, _ in result]
        assert all(s == "https://source.com/article" for s in sources)


def test_extract_links_ignores_non_http():
    with patch("core.sitemap_link_extractor._get_registry") as mock_get_reg:
        mock_reg = MagicMock()
        mock_reg.is_known.return_value = True
        mock_get_reg.return_value = mock_reg

        html = '<a href="/relative/path">Relative</a><a href="mailto:test@example.com">Email</a>'
        result = extract_links("https://example.com/page", html)
        assert len(result) == 0