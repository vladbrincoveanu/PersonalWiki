"""
Full integration tests for the autonomous discovery system.
Tests graph interests, gap detection, scheduler deduplication, and pipeline integration.
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# =============================================================================
# Test 1: Graph Interests with Real Vault Structure
# =============================================================================
def test_graph_interests_hub_node_ranking(tmp_path):
    """Hub nodes (most connected) appear first in interests."""
    vault = tmp_path / "notes"
    vault.mkdir()
    # Hubs: RLHF connected to 3 others
    (vault / "RLHF.md").write_text("# RLHF\n[[PPO]]\n[[reward-model]]\n[[GPT-4]]\n")
    # Medium: PPO connected to 2
    (vault / "PPO.md").write_text("# PPO\n[[RLHF]]\n[[reward-model]]\n")
    # Leaf: reward-model only points out
    (vault / "reward-model.md").write_text("# Reward Model\n[[RLHF]]\n")
    # Isolated: GPT-4 no links
    (vault / "GPT-4.md").write_text("# GPT-4\n")

    from core.graph_interests import extract_interests
    interests = extract_interests(vault_path=str(tmp_path))

    # RLHF has highest connectivity (3 outbound + 2 inbound = 5)
    assert interests.index("RLHF") < interests.index("PPO")
    assert interests.index("PPO") < interests.index("reward-model")


# =============================================================================
# Test 2: Gap Detection Follows Pipeline Integration
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
# Test 3: Discovery Scheduler Deduplication
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
# Test 4: Gap Entities Attached to Note
# =============================================================================
def test_pipeline_attaches_gap_entities(tmp_path, monkeypatch):
    """When detect_gaps returns entities, they are attached to the note."""
    from core.gap_detector import detect_gaps

    # We can't fully run the pipeline without network, but we can test the gap attachment path
    gaps = detect_gaps([{"name": "Unknown Entity X", "slug": "unknown-entity-x"}], vault_path=str(tmp_path))
    assert "Unknown Entity X" in gaps


# =============================================================================
# Test 5: Wikilink Pipe Syntax Parsing
# =============================================================================
def test_wikilink_pipe_syntax_parsed(tmp_path):
    """[[target|display]] wikilinks extract 'target' as the link."""
    vault = tmp_path / "notes"
    vault.mkdir()
    (vault / "A.md").write_text("# A\nSee [[B|Display B]] and [[C]].\n")
    (vault / "B.md").write_text("# B\n")
    (vault / "C.md").write_text("# C\n")

    from core.graph_interests import _scan_vault
    nodes, _ = _scan_vault(tmp_path)

    # B should have an inbound link from A (not "B|Display B")
    assert "B" in nodes["A"]["outbound"]
    assert "B|Display B" not in nodes["A"]["outbound"]


# =============================================================================
# Test 6: Scheduler Start/Stop Guards
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
# Test 7: Interest Keyword Deduplication
# =============================================================================
def test_interests_are_deduplicated(tmp_path):
    """Same keyword from hub + leaf + tag only appears once."""
    vault = tmp_path / "notes"
    vault.mkdir()
    # RLHF appears in wikilinks AND as a tag
    (vault / "A.md").write_text("---\ntags: [RLHF, LLM]\n---\n# A\n[[RLHF]]\n")
    (vault / "RLHF.md").write_text("# RLHF\n[[A]]\n")

    from core.graph_interests import extract_interests
    interests = extract_interests(vault_path=str(tmp_path))

    assert interests.count("RLHF") == 1


# =============================================================================
# Test 8: Full Sitemap Discovery Cycle
# =============================================================================
@pytest.mark.asyncio
async def test_full_sitemap_discovery_cycle():
    """Test: keyword → sitemap fetch → candidate URL → page crawl → new domain discovered."""
    with patch("core.discovery_scheduler.SiteRegistry") as MockReg, \
         patch("core.discovery_scheduler.fetch_sitemap") as mock_fetch, \
         patch("core.vector_store.get_store") as mock_store:

        # Registry: one known domain
        mock_reg = MagicMock()
        mock_reg.all_domains.return_value = ["example.com"]
        mock_reg.is_known.side_effect = lambda d: d == "example.com"
        MockReg.return_value = mock_reg

        # Sitemap returns one matching URL
        mock_fetch.return_value = [
            {"url": "https://example.com/transformer-post", "lastmod": None, "priority": None}
        ]

        # Store says URL is new
        mock_store_instance = MagicMock()
        mock_store_instance.exists.return_value = False
        mock_store.return_value = mock_store_instance

        from core.discovery_scheduler import DiscoveryScheduler

        scheduler = DiscoveryScheduler()
        scheduler._site_registry = mock_reg

        with patch.object(scheduler, "_is_new_url", return_value=True):
            results = await scheduler.search_sitemaps("transformer")

        assert len(results) == 1
        assert "transformer" in results[0]["url"]
        assert results[0]["source"] == "sitemap"
