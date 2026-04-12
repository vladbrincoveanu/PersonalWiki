import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from ingesters import Document


@pytest.mark.asyncio
async def test_extract_news_newspaper3k_success():
    from ingesters.news import extract_news
    long_text = "This is a full article with meaningful content. " * 10
    with patch("ingesters.news._newspaper_extract", return_value=long_text):
        doc = await extract_news("https://example.com/article")
    assert isinstance(doc, Document)
    assert doc.content_type == "article"
    assert "full article" in doc.raw_text


@pytest.mark.asyncio
async def test_extract_news_falls_back_to_crawl4ai_when_newspaper_short():
    from ingesters.news import extract_news
    crawl_text = "Full article content from crawl4ai JS rendering. " * 10
    with patch("ingesters.news._newspaper_extract", return_value="Too short."), \
         patch("ingesters.news.extract_url", AsyncMock(return_value=crawl_text)):
        doc = await extract_news("https://js-heavy.com/article")
    assert "crawl4ai JS rendering" in doc.raw_text


@pytest.mark.asyncio
async def test_extract_news_falls_back_to_crawl4ai_when_newspaper_raises():
    from ingesters.news import extract_news
    crawl_text = "Crawl4ai recovered the content just fine. " * 10
    with patch("ingesters.news._newspaper_extract", side_effect=Exception("download failed")), \
         patch("ingesters.news.extract_url", AsyncMock(return_value=crawl_text)):
        doc = await extract_news("https://example.com/article")
    assert "Crawl4ai recovered" in doc.raw_text


@pytest.mark.asyncio
async def test_extract_news_paywall_stub_when_both_tiers_return_short():
    from ingesters.news import extract_news
    with patch("ingesters.news._newspaper_extract", return_value="Subscribe now."), \
         patch("ingesters.news.extract_url", AsyncMock(return_value="Please log in.")):
        doc = await extract_news("https://nytimes.com/paywalled-article")
    assert doc.raw_text.startswith("[PAYWALLED]")
    assert "nytimes.com" in doc.raw_text
    assert doc.content_type == "article"


@pytest.mark.asyncio
async def test_extract_news_paywall_stub_does_not_raise():
    from ingesters.news import extract_news
    with patch("ingesters.news._newspaper_extract", return_value=""), \
         patch("ingesters.news.extract_url", AsyncMock(side_effect=Exception("403"))):
        doc = await extract_news("https://wsj.com/paywalled")
    assert doc.raw_text.startswith("[PAYWALLED]")
