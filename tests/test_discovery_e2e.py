"""
Full integration tests for the autonomous discovery system.
Tests scheduler deduplication, gap detection.
"""
import pytest
from pathlib import Path


def test_scheduler_deduplicates_against_seen_urls():
    """Verify deduplication logic in DiscoveryScheduler."""
    from core.discovery_scheduler import DiscoveryScheduler
    s = DiscoveryScheduler()
    try:
        s._seen_urls.add("http://example.com/1")
        assert s._is_new_url("http://example.com/1") is False
        assert s._is_new_url("http://example.com/2") is True
    finally:
        s.stop()


def test_gap_detector_not_confused_by_case(tmp_path, monkeypatch):
    """Gap detection is case-insensitive."""
    vault = tmp_path / "notes"
    vault.mkdir()
    (vault / "KV-cache.md").write_text("# KV-cache\n")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path.parent))

    from core.gap_detector import detect_gaps
    entities = [{"name": "KV-cache", "slug": "kv-cache"}]
    gaps = detect_gaps(entities, vault_path=str(tmp_path))
    assert gaps == []
