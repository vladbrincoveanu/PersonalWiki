import pytest
from unittest.mock import patch, MagicMock
from ingesters import Document


FAKE_NITTER_HTML = """
<html><body>
<div class="tweet-header">
  <a class="fullname" href="/hwchase17">Harrison Chase</a>
  <a class="username" href="/hwchase17">@hwchase17</a>
</div>
<div class="tweet-content media-body" dir="auto">
  Continual learning is the key missing piece for AI agents.
</div>
</body></html>
"""

FAKE_THREAD_HTML = """
<html><body>
<div class="tweet-header">
  <a class="fullname" href="/hwchase17">Harrison Chase</a>
  <a class="username" href="/hwchase17">@hwchase17</a>
</div>
<div class="tweet-content media-body" dir="auto">
  Continual learning is the key missing piece for AI agents.
</div>
<div class="tweet-header">
  <a class="fullname" href="/replier">Reply Person</a>
  <a class="username" href="/replier">@replier</a>
</div>
<div class="tweet-content media-body" dir="auto">
  Totally agree with this point.
</div>
</body></html>
"""


def _mock_urlopen(html: str, status: int = 200):
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.read.return_value = html.encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_extract_tweet_returns_document():
    from ingesters.tweet import extract_tweet
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(FAKE_NITTER_HTML)):
        doc = extract_tweet("https://twitter.com/hwchase17/status/123456")
    assert isinstance(doc, Document)
    assert doc.content_type == "tweet"
    assert "hwchase17" in doc.raw_text
    assert "Continual learning" in doc.raw_text


def test_extract_tweet_x_com_url():
    from ingesters.tweet import extract_tweet
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(FAKE_NITTER_HTML)):
        doc = extract_tweet("https://x.com/hwchase17/status/123456")
    assert doc.content_type == "tweet"
    assert "Continual learning" in doc.raw_text


def test_extract_tweet_includes_thread_replies():
    from ingesters.tweet import extract_tweet
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(FAKE_THREAD_HTML)):
        doc = extract_tweet("https://twitter.com/hwchase17/status/123456")
    assert "Continual learning" in doc.raw_text
    assert "Totally agree" in doc.raw_text


def test_extract_tweet_rotates_on_instance_failure():
    from ingesters.tweet import extract_tweet
    side_effects = [
        Exception("Connection refused"),
        _mock_urlopen(FAKE_NITTER_HTML),
    ]
    with patch("urllib.request.urlopen", side_effect=side_effects):
        doc = extract_tweet("https://twitter.com/hwchase17/status/123456")
    assert "Continual learning" in doc.raw_text


def test_extract_tweet_returns_stub_when_all_instances_fail():
    """All Nitter + syndication fail → return NO_TWEET stub, don't raise."""
    from ingesters.tweet import extract_tweet
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        doc = extract_tweet("https://twitter.com/hwchase17/status/123456")
        assert doc.raw_text.startswith("[NO_TWEET]")
        assert doc.content_type == "tweet"


def test_extract_tweet_raises_on_invalid_url():
    from ingesters.tweet import extract_tweet
    with pytest.raises(ValueError, match="Not a valid tweet URL"):
        extract_tweet("https://example.com/not-a-tweet")


def test_extract_tweet_returns_stub_on_non_200():
    """Non-200 response across all instances → return NO_TWEET stub."""
    from ingesters.tweet import extract_tweet
    rate_limited = _mock_urlopen(FAKE_NITTER_HTML, status=429)
    with patch("urllib.request.urlopen", return_value=rate_limited):
        doc = extract_tweet("https://twitter.com/hwchase17/status/123456")
        assert doc.raw_text.startswith("[NO_TWEET]")
        assert doc.content_type == "tweet"


def test_tweet_expanded_instance_pool(monkeypatch):
    """First 4 instances fail, 5th (nitter.esmailelBob.xyz) returns content."""
    import ingesters.tweet as tw

    called = []
    def mock_urlopen(url, timeout=10):
        called.append(str(url))
        # First 4 fail
        if len(called) < 5:
            raise Exception("connection failed")
        # 5th succeeds — return HTML with tweet content
        html = b'<div class="p-text">Hello from tweet</div><span class="username">@user</span>'
        from unittest.mock import MagicMock
        m = MagicMock()
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, *a: None
        m.read.return_value = html
        m.status = 200
        return m

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    doc = tw.extract_tweet("https://twitter.com/user/status/123")
    assert "Hello from tweet" in doc.raw_text
    assert doc.content_type == "tweet"


def test_tweet_syndication_fallback(monkeypatch):
    """All Nitter instances fail, syndication returns content."""
    import ingesters.tweet as tw

    nitter_calls = []
    syndication_calls = []
    def mock_urlopen(url, timeout=10):
        # Handle both string URLs and urllib Request objects
        if hasattr(url, 'get_full_url'):
            url_str = url.get_full_url()
        else:
            url_str = str(url)
        if "syndication.twitter" in url_str:
            syndication_calls.append(url_str)
            html = b'<p class="timeline-message">Syndication tweet text</p>'
            from unittest.mock import MagicMock
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.read.return_value = html
            m.status = 200
            return m
        nitter_calls.append(url_str)
        raise Exception("Nitter down")

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    doc = tw.extract_tweet("https://twitter.com/user/status/123")
    assert "Syndication tweet text" in doc.raw_text
    assert doc.content_type == "tweet"


def test_tweet_all_sources_fail_returns_stub(monkeypatch):
    """All Nitter + syndication fail → return NO_TWEET stub, don't raise."""
    import ingesters.tweet as tw

    def mock_urlopen(url, timeout=10):
        raise Exception("all down")

    from unittest.mock import patch
    with patch("urllib.request.urlopen", mock_urlopen):
        doc = tw.extract_tweet("https://twitter.com/user/status/123")
    assert doc.raw_text.startswith("[NO_TWEET]")
    assert doc.content_type == "tweet"
    assert "[NO_TWEET]" in doc.raw_text


def test_tweet_strips_html_correctly():
    """HTML-stripped tweet text contains actual content, not tags."""
    import ingesters.tweet as tw
    # Test the _strip_tags helper
    html = '<div class="p-text">Hello <b>world</b></div>'
    result = tw._strip_tags(html)
    assert "Hello world" in result
    assert "<" not in result


def test_tweet_nitter_rss_fallback(monkeypatch):
    """All Nitter HTML instances fail, RSS feed returns content."""
    import ingesters.tweet as tw

    rss_calls = []
    def mock_urlopen(url, timeout=10):
        url_str = url.get_full_url() if hasattr(url, 'get_full_url') else str(url)
        if "/rss" in url_str or "/feed" in url_str:
            rss_calls.append(url_str)
            # RSS XML with CDATA description
            xml = '''<?xml version="1.0"?>
<rss><channel><item>
<description><![CDATA[Hello from RSS tweet content]]></description>
</item></channel></rss>'''
            from unittest.mock import MagicMock
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.status = 200
            m.read.return_value = xml.encode()
            return m
        raise Exception("HTML instance failed")

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    doc = tw.extract_tweet("https://twitter.com/user/status/123")
    assert "RSS tweet content" in doc.raw_text
    assert doc.content_type == "tweet"
