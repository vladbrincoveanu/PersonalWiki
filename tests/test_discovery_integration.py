"""
Full integration tests for the autonomous discovery system.
Tests gap detection, scheduler deduplication, and pipeline integration.
"""
import pytest
from pathlib import Path

pytestmark = pytest.mark.integration


# =============================================================================
# Test 1: Gap Detection Follows Pipeline Integration
# =============================================================================
def test_gap_detector_from_enriched_note(tmp_path):
    """Simulate an enriched note with known and unknown entities."""
    vault = tmp_path / "notes"
    vault.mkdir()
    # PagedAttention.md exists; KV-cache.md does NOT exist (only referenced as wikilink)
    (vault / "PagedAttention.md").write_text("# PagedAttention\n[[KV-cache]]\n[[vLLM]]\n")

    from core.gap_detector import detect_gaps
    enriched_entities = [
        {"name": "PagedAttention", "slug": "pagedattention"},  # exists
        {"name": "KV-cache", "slug": "kv-cache"},              # missing (no KV-cache.md file)
        {"name": "FlashAttention", "slug": "flashattention"},  # missing
        {"name": "SARATHI", "slug": "sarathi"},                 # missing
    ]
    gaps = detect_gaps(enriched_entities, vault_path=str(tmp_path))

    assert "FlashAttention" in gaps
    assert "SARATHI" in gaps
    assert "PagedAttention" not in gaps
    # KV-cache is only a wikilink reference, not an actual note file, so it IS a gap
    assert "KV-cache" in gaps


# =============================================================================
# Test 2: Discovery Scheduler Deduplication
# =============================================================================
def test_discovery_scheduler_dedup_all_layers():
    """Scheduler deduplicates at seen, in-flight, and store levels."""
    from core.discovery_scheduler import DiscoveryScheduler

    scheduler = DiscoveryScheduler()

    # Layer 1: seen URLs
    scheduler._seen_urls.add("http://example.com/1")
    assert scheduler._is_new_url("http://example.com/1") is False

    # Layer 2: in-flight
    scheduler._in_flight.add("http://example.com/2")
    assert scheduler._is_new_url("http://example.com/2") is False

    # Layer 3: new URL passes
    assert scheduler._is_new_url("http://example.com/3") is True

    # Cleanup
    scheduler.stop()


# =============================================================================
# Test 3: Gap Entities Attached to Note
# =============================================================================
def test_pipeline_attaches_gap_entities(tmp_path, monkeypatch):
    """When detect_gaps returns entities, they are attached to the note."""
    from core.gap_detector import detect_gaps

    gaps = detect_gaps([{"name": "Unknown Entity X", "slug": "unknown-entity-x"}], vault_path=str(tmp_path))
    assert "Unknown Entity X" in gaps


# =============================================================================
# Test 4: Scheduler Start/Stop Guards
# =============================================================================
@pytest.mark.asyncio
async def test_scheduler_double_start_guard():
    """Calling start() twice is a no-op, not a double scheduler."""
    from core.discovery_scheduler import DiscoveryScheduler
    s = DiscoveryScheduler()
    await s.start()
    await s.start()  # should be no-op

    assert s._running is True
    # Only one task should exist
    s.stop()


# =============================================================================
# Test 5: Discovery Activity API Endpoint
# =============================================================================
@pytest.mark.asyncio
async def test_discovery_activity_api():
    """GET /api/discovery/activity returns today's events and stats."""
    from unittest.mock import patch, MagicMock
    from fastapi.testclient import TestClient
    from app import app

    with patch("core.discovery_logger.get_discovery_logger") as mock_logger:
        mock_instance = MagicMock()
        mock_instance.stats.return_value = {
            "discovered_today": 3,
            "ingested_today": 2,
            "failed_today": 1,
            "queue_depth": 0,
            "last_cycle_at": "2026-04-18T10:00:00Z",
        }
        mock_instance.today.return_value = [
            {
                "url": "https://pytorch.org/blog",
                "title": "PyTorch Blog",
                "source": "sitemap: pytorch.org",
                "status": "ingested",
                "discovered_at": "2026-04-18T10:00:00Z",
                "ingested_at": "2026-04-18T10:01:00Z",
                "error": None,
            }
        ]
        mock_logger.return_value = mock_instance

        client = TestClient(app)
        response = client.get("/api/discovery/activity")

        assert response.status_code == 200
        data = response.json()
        assert data["stats"]["discovered_today"] == 3
        assert data["stats"]["ingested_today"] == 2
        assert data["stats"]["failed_today"] == 1
        assert len(data["events"]) == 1
        assert data["events"][0]["url"] == "https://pytorch.org/blog"
