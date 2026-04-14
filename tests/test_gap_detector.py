import pytest, tempfile
from pathlib import Path

def test_detects_entities_not_in_vault(tmp_path):
    vault = tmp_path / "notes"
    vault.mkdir()
    # Existing note
    (vault / "existing.md").write_text("# Existing Note\n")

    from core.gap_detector import detect_gaps
    entities = [
        {"name": "Existing Note", "slug": "existing"},
        {"name": "Missing Entity", "slug": "missing-entity"},
    ]
    gaps = detect_gaps(entities, vault_path=str(tmp_path))
    assert "Missing Entity" in gaps
    assert "Existing Note" not in gaps

def test_returns_empty_when_all_entities_exist(tmp_path):
    vault = tmp_path / "notes"
    vault.mkdir()
    (vault / "paged-attention.md").write_text("# PagedAttention\n")

    from core.gap_detector import detect_gaps
    entities = [{"name": "PagedAttention", "slug": "paged-attention"}]
    gaps = detect_gaps(entities, vault_path=str(tmp_path))
    assert gaps == []

def test_case_insensitive_match(tmp_path):
    vault = tmp_path / "notes"
    vault.mkdir()
    (vault / "paged-attention.md").write_text("# PagedAttention\n")

    from core.gap_detector import detect_gaps
    entities = [{"name": "PagedAttention", "slug": "paged-attention"}]
    gaps = detect_gaps(entities, vault_path=str(tmp_path))
    assert gaps == []
