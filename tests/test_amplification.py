import pytest
import asyncio
from unittest.mock import patch, MagicMock


def test_amplify_from_note_does_nothing():
    """_amplify_from_note must be a no-op — keywords are user-owned only."""
    from core.discovery_scheduler import DiscoveryScheduler

    # Prevent _blocking_refresh from running so _keywords stays empty
    with patch.object(DiscoveryScheduler, '_blocking_refresh'):
        scheduler = DiscoveryScheduler()
        original_keywords = list(scheduler._keywords)

    # Even if _amplify_from_note is called with note content, no keywords should be added
    asyncio.run(scheduler._amplify_from_note({
        "title": "Test Note",
        "raw_text": "machine learning transformers neural networks"
    }))
    assert scheduler._keywords == original_keywords, "amplification should not add keywords"


def test_get_explore_keywords_returns_empty():
    """_get_explore_keywords must return empty list — exploration disabled."""
    from core.discovery_scheduler import DiscoveryScheduler

    with patch.object(DiscoveryScheduler, '_blocking_refresh'):
        scheduler = DiscoveryScheduler()

    assert scheduler._get_explore_keywords() == [], "_get_explore_keywords must return empty list"
