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


def test_returns_empty_when_vault_path_is_empty_string(monkeypatch):
    """When VAULT_PATH env var is empty string, detect_gaps must return [] (not all entities).

    Regression: Path('') becomes PosixPath('.') whose str() is '.' not ''.
    The condition 'if not str(vault_path)' must catch this before Path() is constructed.
    """
    import os
    from core.gap_detector import detect_gaps

    # Simulate VAULT_PATH="" (empty string, not None)
    monkeypatch.setenv("VAULT_PATH", "")

    entities = [
        {"name": "Some Entity", "slug": "some-entity"},
        {"name": "Another Entity", "slug": "another-entity"},
    ]
    gaps = detect_gaps(entities, vault_path=None)
    # Empty vault path = "we don't know" = safe to return [] (no uncontrolled search explosion)
    assert gaps == [], f"Expected [] for empty VAULT_PATH, got {gaps}"
