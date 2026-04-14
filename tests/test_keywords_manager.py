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
    def test_purge_deletes_files_containing_keyword(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "doc1.md").write_text("python is great")
        (vault / "doc2.md").write_text("rust is fast")
        (vault / "doc3.md").write_text("python and rust")
        deleted = purge_keyword("python", vault)
        assert len(deleted) == 2
        assert not (vault / "doc1.md").exists()
        assert not (vault / "doc3.md").exists()
        assert (vault / "doc2.md").exists()

    def test_purge_matches_raw_text_not_just_wikilink(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "doc1.md").write_text("Check [[python]] for info")
        (vault / "doc2.md").write_text("python programming")
        (vault / "doc3.md").write_text("use python3")
        deleted = purge_keyword("python", vault)
        assert len(deleted) == 3
        assert not (vault / "doc1.md").exists()
        assert not (vault / "doc2.md").exists()
        assert not (vault / "doc3.md").exists()
