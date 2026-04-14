import pytest
from unittest.mock import patch, MagicMock
from vault.entity_status import fetch_entity_status, _is_library_entity, _build_prose


def test_is_library_entity_filters_correctly():
    assert (
        _is_library_entity({"name": "PyTorch", "slug": "pytorch", "type": "library"})
        is True
    )
    assert (
        _is_library_entity({"name": "React", "slug": "react", "type": "framework"})
        is True
    )
    assert (
        _is_library_entity({"name": "crawl4ai", "slug": "crawl4ai", "type": "tool"})
        is True
    )
    assert (
        _is_library_entity({"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"})
        is False
    )
    assert (
        _is_library_entity(
            {
                "name": "Attention Mechanism",
                "slug": "attention-mechanism",
                "type": "concept",
            }
        )
        is False
    )
    assert (
        _is_library_entity(
            {"name": "Yann LeCun", "slug": "yann-lecun", "type": "person"}
        )
        is False
    )
    assert (
        _is_library_entity(
            {"name": "Stanford", "slug": "stanford", "type": "institution"}
        )
        is False
    )


def test_fetch_entity_status_returns_structured_results():
    entities = [
        {"name": "PyTorch", "slug": "pytorch", "type": "library"},
        {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
    ]
    mock_results = {
        "PyTorch": {
            "version": "v2.5.1",
            "status": "actively maintained",
            "source": "PyPI",
        },
        "MIMIC-IV": None,
    }

    def mock_search(name, slug):
        return mock_results.get(name)

    with patch("vault.entity_status._search_library_status", mock_search):
        result = fetch_entity_status(entities)

    assert len(result) == 1
    assert result[0]["name"] == "PyTorch"
    assert result[0]["version"] == "v2.5.1"
    assert result[0]["status"] == "actively maintained"


def test_build_prose_generates_connected_text():
    statuses = [
        {
            "name": "PyTorch",
            "version": "v2.5.1",
            "status": "actively maintained",
            "source": "PyPI",
        },
        {
            "name": "crawl4ai",
            "version": "v0.3.0",
            "status": "actively maintained",
            "source": "GitHub",
        },
    ]
    prose = _build_prose(statuses)
    assert "PyTorch" in prose
    assert "crawl4ai" in prose
    assert "v2.5.1" in prose
    assert "v0.3.0" in prose
    assert isinstance(prose, str)
    assert len(prose) > 0


def test_fetch_entity_status_empty_when_no_library_entities():
    entities = [
        {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
        {
            "name": "Attention Mechanism",
            "slug": "attention-mechanism",
            "type": "concept",
        },
    ]
    result = fetch_entity_status(entities)
    assert result == []
