import pytest

import core.bm25_index as bm25
import core.mcp_server as mcp


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(bm25, "NOTES_DIR", tmp_path)
    bm25.invalidate_index()
    note = tmp_path / "vic" / "AAPL" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        '---\ntitle: "Apple Inc."\nticker: "AAPL"\nauthor: "someuser"\n---\n\nBody.\n',
        encoding="utf-8",
    )
    yield tmp_path
    bm25.invalidate_index()


def test_search_returns_the_matching_note(vault):
    output = mcp.search_vault_notes("AAPL", limit=5)
    assert "Apple Inc." in output
    assert "note.md" in output


def test_search_reports_no_results_cleanly(vault):
    assert "No notes found" in mcp.search_vault_notes("zzzznomatch", limit=5)


def test_search_does_not_embed(vault, monkeypatch):
    def boom(_text):
        raise AssertionError("embeddings must not be used by the MCP search path")

    monkeypatch.setattr("core.embeddings.embed", boom)
    assert "Apple Inc." in mcp.search_vault_notes("AAPL", limit=5)
