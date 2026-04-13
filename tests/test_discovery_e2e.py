import pytest, asyncio, os, tempfile
from pathlib import Path

def test_graph_interests_extracts_from_vault(tmp_path, monkeypatch):
    """Verify extract_interests works against a small vault."""
    vault = tmp_path / "notes"
    vault.mkdir()
    (vault / "RLHF.md").write_text("# RLHF\n[[PPO]]\n[[reward-model]]\n")
    (vault / "PPO.md").write_text("# PPO\n[[RLHF]]\n")
    (vault / "reward-model.md").write_text("# Reward Model\n")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path.parent))

    from core.graph_interests import extract_interests
    interests = extract_interests(vault_path=str(tmp_path.parent))
    # RLHF has highest connectivity, should appear
    assert "RLHF" in interests

def test_scheduler_deduplicates_against_seen_urls():
    """Verify deduplication logic in DiscoveryScheduler."""
    from core.discovery_scheduler import DiscoveryScheduler
    s = DiscoveryScheduler()
    s._seen_urls.add("http://example.com/1")
    assert s._is_new_url("http://example.com/1") is False
    assert s._is_new_url("http://example.com/2") is True

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
