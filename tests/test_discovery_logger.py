import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

def test_discovery_event_dataclass():
    """DiscoveryEvent stores all fields correctly."""
    from core.discovery_logger import DiscoveryEvent

    event = DiscoveryEvent(
        url="https://pytorch.org/blog/25",
        title="PyTorch 2.5",
        source="sitemap: pytorch.org",
        status="ingested",
        discovered_at="2026-04-18T10:00:00Z",
        ingested_at="2026-04-18T10:01:00Z",
        error=None,
    )
    assert event.url == "https://pytorch.org/blog/25"
    assert event.status == "ingested"
    assert event.title == "PyTorch 2.5"


def test_discovery_logger_records_event(tmp_path):
    """Logger records a discovery event."""
    from core.discovery_logger import DiscoveryLogger

    with patch("core.discovery_logger._LOG_FILE", tmp_path / "log.json"):
        logger = DiscoveryLogger()
        logger.record("https://example.com/article", "Example Article", "sitemap: example.com", "enqueued")

        events = logger.today()
        assert len(events) == 1
        assert events[0].url == "https://example.com/article"
        assert events[0].title == "Example Article"
        assert events[0].status == "enqueued"


def test_discovery_logger_updates_status(tmp_path):
    """Logger can update an existing event's status."""
    from core.discovery_logger import DiscoveryLogger

    with patch("core.discovery_logger._LOG_FILE", tmp_path / "log.json"):
        logger = DiscoveryLogger()
        logger.record("https://example.com/article", "Example", "sitemap: example.com", "enqueued")
        logger.update_status("https://example.com/article", "ingested")

        events = logger.today()
        assert events[0].status == "ingested"
        assert events[0].ingested_at is not None


def test_discovery_logger_stats(tmp_path):
    """Logger computes today's stats correctly."""
    from core.discovery_logger import DiscoveryLogger

    with patch("core.discovery_logger._LOG_FILE", tmp_path / "log.json"):
        logger = DiscoveryLogger()
        logger.record("https://a.com/1", "A", "sitemap: a.com", "enqueued")
        logger.record("https://b.com/2", "B", "keyword: test", "enqueued")
        logger.update_status("https://a.com/1", "ingested")
        logger.update_status("https://b.com/2", "failed", error="Quality gate rejected")

        stats = logger.stats()
        assert stats["discovered_today"] == 2
        assert stats["ingested_today"] == 1
        assert stats["failed_today"] == 1


def test_discovery_logger_today_only(tmp_path):
    """Logger returns only today's events."""
    from core.discovery_logger import DiscoveryLogger

    with patch("core.discovery_logger._LOG_FILE", tmp_path / "log.json"):
        logger = DiscoveryLogger()
        yesterday_event = {
            "url": "https://old.com/article",
            "title": "Old Article",
            "source": "sitemap: old.com",
            "status": "ingested",
            "discovered_at": "2026-04-17T10:00:00Z",
            "ingested_at": "2026-04-17T10:01:00Z",
            "error": None,
        }
        logger._events.append(yesterday_event)
        logger._persist()

        events = logger.today()
        assert all(e["discovered_at"].startswith("2026-04-18") for e in events)
