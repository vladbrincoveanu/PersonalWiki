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


def test_extract_tweet_raises_when_all_instances_fail():
    from ingesters.tweet import extract_tweet
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        with pytest.raises(ValueError, match="All Nitter instances"):
            extract_tweet("https://twitter.com/hwchase17/status/123456")


def test_extract_tweet_raises_on_invalid_url():
    from ingesters.tweet import extract_tweet
    with pytest.raises(ValueError, match="Not a valid tweet URL"):
        extract_tweet("https://example.com/not-a-tweet")


def test_extract_tweet_falls_through_on_non_200():
    from ingesters.tweet import extract_tweet
    rate_limited = _mock_urlopen(FAKE_NITTER_HTML, status=429)
    with patch("urllib.request.urlopen", return_value=rate_limited):
        with pytest.raises(ValueError, match="All Nitter instances"):
            extract_tweet("https://twitter.com/hwchase17/status/123456")
