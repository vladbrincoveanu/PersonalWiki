import pytest, asyncio
from unittest.mock import patch, MagicMock


def test_update_keyword_score_positive():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    scheduler._keywords.append("test-kw")
    scheduler._update_keyword_score("test-kw", +1)
    assert scheduler._keyword_scores.get("test-kw") == 1


def test_update_keyword_score_triggers_suppress():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    scheduler._keywords.append("bad-kw")
    with patch.object(scheduler, 'suppress_keyword') as mock_suppress:
        scheduler._update_keyword_score("bad-kw", -6)
        mock_suppress.assert_called_once_with("bad-kw")


def test_amplify_from_note_adds_keywords():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()

    with patch("core.keyword_extractor.extract_keywords_from_note",
               return_value=["new-kw-1", "new-kw-2"]):
        asyncio.run(scheduler._amplify_from_note({
            "title": "Test Note",
            "raw_text": "Some content about transformers."
        }))

    assert "new-kw-1" in scheduler._keywords
    assert "new-kw-2" in scheduler._keywords


def test_get_explore_keywords():
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    keywords = scheduler._get_explore_keywords()
    assert len(keywords) <= 2
    assert isinstance(keywords, list)
