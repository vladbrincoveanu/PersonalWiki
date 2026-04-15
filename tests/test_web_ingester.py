import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from ingesters.web import extract_url

@pytest.mark.asyncio
async def test_extract_url_returns_markdown():
    mock_result = MagicMock()
    mock_result.markdown = "# PagedAttention\n\nEfficient memory management."
    mock_result.success = True

    with patch("ingesters.web.AsyncWebCrawler") as MockCrawler:
        instance = AsyncMock()
        instance.arun = AsyncMock(return_value=mock_result)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        MockCrawler.return_value = instance

        result = await extract_url("https://arxiv.org/abs/2309.06180")

    assert "PagedAttention" in result
    assert "Efficient memory management." in result

@pytest.mark.asyncio
async def test_extract_url_raises_on_failure():
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.markdown = ""

    with patch("ingesters.web.AsyncWebCrawler") as MockCrawler:
        instance = AsyncMock()
        instance.arun = AsyncMock(return_value=mock_result)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        MockCrawler.return_value = instance

        with pytest.raises(ValueError, match="Failed to extract"):
            await extract_url("https://example.com/404")
