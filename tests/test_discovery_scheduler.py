import pytest, asyncio
from unittest.mock import patch, MagicMock

def test_discovery_scheduler_initializes():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    assert scheduler._running is False
    assert scheduler._keywords == []

def test_deduplication_against_seen_urls():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    scheduler._seen_urls.add("https://arxiv.org/abs/1234")
    assert scheduler._is_new_url("https://arxiv.org/abs/1234") is False
    assert scheduler._is_new_url("https://arxiv.org/abs/9999") is True

@pytest.mark.asyncio
async def test_keyword_refresh():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    with patch("core.graph_interests.extract_interests", return_value=["RLHF", "KV-cache"]):
        await scheduler._refresh_keywords()
    assert scheduler._keywords == ["RLHF", "KV-cache"]
