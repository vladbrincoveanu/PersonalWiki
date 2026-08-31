import pytest
from ingesters.router import _validate_external_url, route_url


def test_route_url_tweet():
    assert route_url("https://twitter.com/user/status/123") == "tweet"
    assert route_url("https://x.com/user/status/456") == "tweet"
    assert route_url("http://twitter.com/user/status/789") == "tweet"


def test_route_url_youtube():
    assert route_url("https://www.youtube.com/watch?v=abc") == "youtube"
    assert route_url("https://youtube.com/watch?v=xyz") == "youtube"


def test_route_url_pdf():
    assert route_url("https://arxiv.org/pdf/2510.18518") == "pdf"
    assert route_url("https://arxiv.org/abs/2510.18518") == "pdf"
    assert route_url("https://example.com/paper.pdf") == "pdf"
    assert route_url("https://example.com/doc.pdf?download=1") == "pdf"


def test_route_url_news():
    assert route_url("https://example.com/article") == "news"
    assert route_url("https://news.site.com/story/123") == "news"
    assert route_url("https://blog.post.com/2024/01/01/title") == "news"


def test_external_url_rejects_private_destinations():
    with pytest.raises(ValueError, match="public address"):
        _validate_external_url("http://127.0.0.1:8080/admin")


def test_external_url_rejects_embedded_credentials():
    with pytest.raises(ValueError, match="credentials"):
        _validate_external_url("https://user:password@example.com/article")
