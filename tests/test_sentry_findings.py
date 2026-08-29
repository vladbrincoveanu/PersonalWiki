from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_trigger_discovery_awaits_cycle(monkeypatch):
    import app

    scheduler = MagicMock()
    scheduler.trigger_cycle = AsyncMock()
    monkeypatch.setattr(app, "_get_scheduler", AsyncMock(return_value=scheduler))

    result = await app.trigger_discovery()

    assert result == {"status": "triggered"}
    scheduler.trigger_cycle.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_discovery_reports_scheduler_runtime_errors(monkeypatch):
    import app

    scheduler = MagicMock()
    scheduler.trigger_cycle = AsyncMock(side_effect=RuntimeError("scheduler is not running"))
    monkeypatch.setattr(app, "_get_scheduler", AsyncMock(return_value=scheduler))

    with pytest.raises(HTTPException) as exc_info:
        await app.trigger_discovery()

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "scheduler is not running"


def test_merge_entities_retains_image_entities_and_deduplicates():
    from pipeline import _merge_entities

    image_entity = {"name": "Vision Transformer", "slug": "vision-transformer", "source": "image"}
    duplicate_from_text = {"name": "Vision Transformer", "slug": "vision-transformer", "source": "text"}
    text_entity = {"name": "PyTorch", "slug": "pytorch", "source": "text"}

    merged = _merge_entities([image_entity], [duplicate_from_text, text_entity])

    assert merged == [image_entity, text_entity]


def test_inject_keywords_after_section_content():
    from vault.writer import _inject_keywords_section

    body = "## Summary\nSummary content.\n\n## Key Facts\n- Fact.\n"

    result = _inject_keywords_section(body, ["python"])

    assert result == (
        "## Summary\nSummary content.\n\n"
        "## Keywords\n[[python]]\n\n"
        "## Key Facts\n- Fact.\n"
    )


def test_inject_keywords_replaces_section_without_joining_headings():
    from vault.writer import _inject_keywords_section

    body = "## Summary\nSummary.\n\n## Keywords\n[[old]]\n\n## Key Facts\n- Fact.\n"

    result = _inject_keywords_section(body, ["python", "testing"])

    assert result == (
        "## Summary\nSummary.\n\n"
        "## Keywords\n[[python]] · [[testing]]\n\n"
        "## Key Facts\n- Fact.\n"
    )
