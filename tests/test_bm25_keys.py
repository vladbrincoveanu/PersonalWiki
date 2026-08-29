import pytest

import core.bm25_index as bm25


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(bm25, "NOTES_DIR", tmp_path)
    bm25.invalidate_index()
    yield tmp_path
    bm25.invalidate_index()


def _write(root, rel, frontmatter, body=""):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    return path


def test_finds_note_in_a_subdirectory(vault):
    _write(vault, "vic/AAPL/note.md", 'ticker: "AAPL"\ncompany: "Apple Inc."')
    results = bm25.bm25_search("AAPL", top_k=5)
    assert results and results[0]["path"].endswith("vic/AAPL/note.md")


def test_keeps_a_zero_idf_key_match(vault):
    _write(vault, "aapl.md", 'ticker: "AAPL"')
    _write(vault, "msft.md", 'ticker: "MSFT"')
    results = bm25.bm25_search("AAPL", top_k=5)
    assert results and results[0]["path"].endswith("aapl.md")
    assert all(not result["path"].endswith("msft.md") for result in results)


def test_matches_on_company_key(vault):
    _write(vault, "vic/AAPL/note.md", 'ticker: "AAPL"\ncompany: "Apple Inc."')
    results = bm25.bm25_search("Apple", top_k=5)
    assert results and results[0]["path"].endswith("vic/AAPL/note.md")


def test_matches_on_author_key(vault):
    _write(vault, "vic/AAPL/note.md", 'ticker: "AAPL"\nauthor: "someuser"')
    results = bm25.bm25_search("someuser", top_k=5)
    assert results and results[0]["path"].endswith("vic/AAPL/note.md")


def test_body_text_is_not_indexed(vault):
    _write(vault, "vic/AAPL/note.md", 'ticker: "AAPL"', body="a distinctive spinoff thesis")
    assert bm25.bm25_search("spinoff", top_k=5) == []


def test_content_index_keeps_body_text_for_hybrid_search(vault):
    _write(vault, "vic/AAPL/note.md", 'ticker: "AAPL"', body="a distinctive spinoff thesis")
    results = bm25.bm25_search("spinoff", top_k=5, include_body=True)
    assert results and results[0]["path"].endswith("vic/AAPL/note.md")


def test_indexes_canonical_ingested_date_key(vault):
    _write(vault, "plain.md", "ingested: 2026-04-10")
    results = bm25.bm25_search("2026-04-10", top_k=5)
    assert results and results[0]["path"].endswith("plain.md")


def test_empty_metadata_corpus_returns_no_results(vault):
    _write(vault, "empty.md", "", body="body is deliberately not indexed")
    assert bm25.bm25_search("anything", top_k=5) == []


def test_indexes_top_level_notes_too(vault):
    _write(vault, "plain.md", 'title: "Llama 2"\ntype: "paper"')
    results = bm25.bm25_search("Llama", top_k=5)
    assert results and results[0]["path"].endswith("plain.md")


def test_list_valued_keys_are_indexed(vault):
    _write(vault, "plain.md", 'title: "X"\nkeywords:\n  - retrieval\n  - agents')
    results = bm25.bm25_search("retrieval", top_k=5)
    assert results and results[0]["path"].endswith("plain.md")
