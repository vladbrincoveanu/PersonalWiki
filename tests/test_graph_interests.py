import pytest, tempfile, os
from pathlib import Path

def test_extracts_hub_nodes(tmp_path):
    vault = tmp_path / "notes"
    vault.mkdir()
    (vault / "A.md").write_text("# A\n[[B]]\n[[C]]\n")
    (vault / "B.md").write_text("# B\n[[C]]\n")
    (vault / "C.md").write_text("# C\n")

    import core.graph_interests as gi
    interests = gi.extract_interests(vault_path=str(tmp_path))

    # C has 2 inbound links (hub), should appear
    assert "C" in interests

def test_extracts_tags_from_frontmatter(tmp_path):
    vault = tmp_path / "notes"
    vault.mkdir()
    (vault / "tagged.md").write_text("---\ntags: [RLHF, LLM]\n---\n# Tagged\n")

    import core.graph_interests as gi
    interests = gi.extract_interests(vault_path=str(tmp_path))
    assert any("RLHF" in i or "LLM" in i for i in interests)

def test_returns_list_of_strings(tmp_path):
    vault = tmp_path / "notes"
    vault.mkdir()
    (vault / "note.md").write_text("# Note\n[[Other]]\n")

    import core.graph_interests as gi
    interests = gi.extract_interests(vault_path=str(tmp_path))
    assert isinstance(interests, list)
    assert all(isinstance(i, str) for i in interests)
