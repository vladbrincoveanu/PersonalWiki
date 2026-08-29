"""Tests for keywords_manager module."""

import pytest
from pathlib import Path

from core.keywords_manager import (
    load_manual_keywords,
    save_manual_keywords,
    add_keyword,
    remove_keyword,
    purge_keyword,
)


class TestLoadManualKeywords:
    def test_load_returns_empty_list_when_file_missing(self, tmp_path):
        result = load_manual_keywords(tmp_path / ".interests")
        assert result == []

    def test_save_and_load_roundtrip(self, tmp_path):
        keywords = ["python", "rust", "webassembly", "  spaces  "]
        path = tmp_path / ".interests"
        save_manual_keywords(keywords, path)
        loaded = load_manual_keywords(path)
        assert loaded == ["python", "rust", "webassembly", "spaces"]

    def test_load_ignores_comments_and_blank_lines(self, tmp_path):
        path = tmp_path / ".interests"
        path.write_text("# comment\npython\n\nrust\n# another\n")
        result = load_manual_keywords(path)
        assert result == ["python", "rust"]


class TestAddKeyword:
    def test_add_keyword_appends_without_duplicates(self, tmp_path):
        path = tmp_path / ".interests"
        path.write_text("python\nrust\n")
        add_keyword("go", path)
        content = path.read_text()
        assert content == "python\nrust\ngo\n"

    def test_add_duplicate_raises(self, tmp_path):
        path = tmp_path / ".interests"
        path.write_text("python\nrust\n")
        with pytest.raises(ValueError, match="already exists"):
            add_keyword("rust", path)

    def test_add_creates_file_if_missing(self, tmp_path):
        path = tmp_path / ".interests"
        add_keyword("python", path)
        assert path.exists()
        assert path.read_text().strip() == "python"


class TestRemoveKeyword:
    def test_remove_keyword_deletes_from_file(self, tmp_path):
        path = tmp_path / ".interests"
        path.write_text("python\nrust\ngo\n")
        remove_keyword("rust", path)
        assert path.read_text() == "python\ngo\n"

    def test_remove_nonexistent_raises(self, tmp_path):
        path = tmp_path / ".interests"
        path.write_text("python\n")
        with pytest.raises(KeyError, match="not found"):
            remove_keyword("rust", path)


class TestPurgeKeyword:
    def test_purge_strips_wikilinks_but_keeps_file_with_real_content(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        content = "# python\n\n[[python]] is a programming language.\n## Summary\nGreat language."
        (vault / "doc1.md").write_text(content, encoding="utf-8")
        (vault / "doc2.md").write_text("rust is fast", encoding="utf-8")
        deleted = purge_keyword("python", vault)
        assert len(deleted) == 0
        assert (vault / "doc1.md").exists()
        # wikilink stripped but rest of content preserved
        assert "python is a programming language" in (vault / "doc1.md").read_text(encoding="utf-8")
        assert "[[python]]" not in (vault / "doc1.md").read_text(encoding="utf-8")
        assert (vault / "doc2.md").exists()

    def test_purge_deletes_orphan_stub_with_only_wikilink(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "stub.md").write_text("# python\n\n[[python]]\n", encoding="utf-8")
        (vault / "real.md").write_text("# python\n\n[[python]]\n## Summary\nA great language.\n", encoding="utf-8")
        deleted = purge_keyword("python", vault)
        assert len(deleted) == 1
        assert str(vault / "stub.md") in deleted
        assert not (vault / "stub.md").exists()
        assert (vault / "real.md").exists()

    def test_purge_deletes_orphan_with_keyword_title_no_wikilink(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        # filename stem matches keyword so it's detected as a title-orphan
        (vault / "bitcoin.md").write_text("# bitcoin\n\n", encoding="utf-8")
        deleted = purge_keyword("bitcoin", vault)
        assert len(deleted) == 1
        assert not (vault / "bitcoin.md").exists()

    def test_purge_preserves_frontmatter(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        fm = "---\ntitle: python\nsource: https://example.com\n---\n[[python]] is great.\n"
        (vault / "doc.md").write_text(fm, encoding="utf-8")
        purge_keyword("python", vault)
        content = (vault / "doc.md").read_text(encoding="utf-8")
        assert content.startswith("---")
        assert "title: python" in content
        assert "[[python]]" not in content
        assert "is great." in content

    def test_purge_ignores_files_without_wikilink(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "doc.md").write_text("python is a language", encoding="utf-8")
        deleted = purge_keyword("python", vault)
        assert len(deleted) == 0
        assert (vault / "doc.md").exists()


class TestCascadeDelete:
    def test_remove_keyword_cascade_delete_last_keyword(self, tmp_path):
        """Removing last keyword from a note deletes the file entirely."""
        vault = tmp_path / "vault"
        vault.mkdir()
        keywords_file = tmp_path / "_keywords"
        keywords_file.write_text("machine-learning\n")

        note = vault / "ml-article.md"
        note.write_text("---\nkeywords: [machine-learning]\n---\n# ML Article\nContent here.")

        result = remove_keyword("machine-learning", keywords_file, vault_path=vault)

        assert not note.exists(), "note with only this keyword should be deleted"
        assert str(note) in result["deleted"]

    def test_remove_keyword_partial_remove_multi_keyword(self, tmp_path):
        """Removing a keyword from a note with multiple keywords just strips that keyword."""
        vault = tmp_path / "vault"
        vault.mkdir()
        keywords_file = tmp_path / "_keywords"
        keywords_file.write_text("python\nmachine-learning\n")

        note = vault / "ml-article.md"
        note.write_text("---\nkeywords: [python, machine-learning]\n---\n# ML Article\n[[python]] and [[machine-learning]] content.")

        result = remove_keyword("machine-learning", keywords_file, vault_path=vault)

        assert note.exists(), "note should be kept"
        assert str(note) not in result["deleted"]
        content = note.read_text()
        assert "[[machine-learning]]" not in content, "wikilink should be stripped"
        assert "machine-learning" in content, "keyword should remain as plain text"

    def test_remove_keyword_does_not_delete_multi_keyword_note_during_purge(self, tmp_path):
        """A note kept for another keyword must survive the follow-up purge."""
        vault = tmp_path / "vault"
        vault.mkdir()
        keywords_file = tmp_path / "_keywords"
        keywords_file.write_text("python\nrust\n")

        note = vault / "python.md"
        note.write_text("---\nkeywords: [python, rust]\n---\n[[python]]\n")

        result = remove_keyword("python", keywords_file, vault_path=vault)

        assert note.exists()
        assert str(note) in result["stripped"]
        content = note.read_text()
        assert "- rust" in content
        assert "python" in content
        assert "[[python]]" not in content

    def test_remove_keyword_calls_vector_store_delete(self, tmp_path):
        """Remove keyword should also delete from vector store for fully-deleted files."""
        from unittest.mock import MagicMock, patch

        vault = tmp_path / "vault"
        vault.mkdir()
        keywords_file = tmp_path / "_keywords"
        keywords_file.write_text("machine-learning\n")

        note1 = vault / "article-about-ml.md"
        note1.write_text("---\nkeywords: [machine-learning]\n---\n# ML Article\nContent here.")

        mock_store = MagicMock()
        with patch("core.vector_store.get_store", return_value=mock_store):
            result = remove_keyword("machine-learning", keywords_file, vault_path=vault)

        assert not note1.exists()
        mock_store.delete.assert_called_once_with(str(note1))

    def test_remove_keyword_still_deletes_if_store_fails(self, tmp_path):
        """File deletion from vault still happens even if vector store fails."""
        from unittest.mock import MagicMock, patch

        vault = tmp_path / "vault"
        vault.mkdir()
        keywords_file = tmp_path / "_keywords"
        keywords_file.write_text("machine-learning\n")

        note1 = vault / "article-about-ml.md"
        note1.write_text("---\nkeywords: [machine-learning]\n---\n# ML Article\nContent here.")

        with patch("core.vector_store.get_store", side_effect=Exception("store unavailable")):
            result = remove_keyword("machine-learning", keywords_file, vault_path=vault)

        assert not note1.exists(), "file should be deleted from vault even if store fails"
        assert str(note1) in result["deleted"]

    def test_remove_keyword_backward_compat_no_vault_path(self, tmp_path):
        """remove_keyword without vault_path still removes from _keywords file."""
        keywords_file = tmp_path / "_keywords"
        keywords_file.write_text("python\nrust\n")
        remove_keyword("rust", keywords_file)
        assert keywords_file.read_text() == "python\n"

    def test_remove_keyword_raises_if_not_found(self, tmp_path):
        """remove_keyword still raises KeyError if keyword missing."""
        keywords_file = tmp_path / "_keywords"
        keywords_file.write_text("python\n")
        with pytest.raises(KeyError, match="not found"):
            remove_keyword("rust", keywords_file)


class TestCheckKeywordImpact:
    def test_impact_single_keyword_deletes(self, tmp_path):
        from core.keywords_manager import _check_keyword_impact
        vault = tmp_path / "vault"
        vault.mkdir()
        note = vault / "doc.md"
        note.write_text("---\nkeywords: [python]\n---\nBody.")
        impact = _check_keyword_impact("python", vault)
        assert str(note) in impact["delete"]
        assert not impact["remove_keyword_only"]

    def test_impact_multi_keyword_strips(self, tmp_path):
        from core.keywords_manager import _check_keyword_impact
        vault = tmp_path / "vault"
        vault.mkdir()
        note = vault / "doc.md"
        note.write_text("---\nkeywords: [python, rust]\n---\nBody [[python]] [[rust]].")
        impact = _check_keyword_impact("python", vault)
        assert str(note) in impact["remove_keyword_only"]
        assert not impact["delete"]

    def test_impact_source_keyword_only_keyword_deletes(self, tmp_path):
        from core.keywords_manager import _check_keyword_impact
        vault = tmp_path / "vault"
        vault.mkdir()
        note = vault / "doc.md"
        note.write_text("---\nsource_keyword: python\n---\nBody.")
        impact = _check_keyword_impact("python", vault)
        assert str(note) in impact["delete"]

    def test_impact_no_matching_keyword_ignores(self, tmp_path):
        from core.keywords_manager import _check_keyword_impact
        vault = tmp_path / "vault"
        vault.mkdir()
        note = vault / "doc.md"
        note.write_text("---\nkeywords: [rust]\n---\nBody.")
        impact = _check_keyword_impact("python", vault)
        assert not impact["delete"]
        assert not impact["remove_keyword_only"]


class TestSuppressRemoved:
    def test_suppress_keyword_removed(self):
        """suppress_keyword should no longer exist."""
        from core import keywords_manager
        assert not hasattr(keywords_manager, "suppress_keyword"), "suppress_keyword should be removed"

    def test_load_suppressed_keywords_removed(self):
        """load_suppressed_keywords should no longer exist."""
        from core import keywords_manager
        assert not hasattr(keywords_manager, "load_suppressed_keywords"), "load_suppressed_keywords should be removed"
