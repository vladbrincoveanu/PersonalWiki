import asyncio
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi import UploadFile


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


@pytest.mark.asyncio
async def test_save_upload_enforces_size_limit(monkeypatch):
    import app

    monkeypatch.setattr(app, "_MAX_UPLOAD_BYTES", 4)
    upload = UploadFile(filename="large.pdf", file=BytesIO(b"12345"))

    with pytest.raises(HTTPException) as exc_info:
        await app._save_upload(upload)

    assert exc_info.value.status_code == 413


def test_purge_expired_previews_removes_cached_file(tmp_path):
    import app

    previous = app._preview_cache.copy()
    try:
        app._preview_cache.clear()
        expired_file = tmp_path / "expired.pdf"
        fresh_file = tmp_path / "fresh.pdf"
        expired_file.write_bytes(b"expired")
        fresh_file.write_bytes(b"fresh")
        now = 1_000.0
        app._preview_cache.update({
            "expired": {"tmp_path": str(expired_file), "created_at": now - app._PREVIEW_TTL - 1},
            "fresh": {"tmp_path": str(fresh_file), "created_at": now},
        })

        assert app._purge_expired_previews(now=now) == 1
        assert not expired_file.exists()
        assert fresh_file.exists()
        assert "expired" not in app._preview_cache
        assert "fresh" in app._preview_cache
    finally:
        app._preview_cache.clear()
        app._preview_cache.update(previous)


@pytest.mark.asyncio
async def test_ingest_run_rejects_missing_preview_source():
    import app

    class RequestWithoutSource:
        async def json(self):
            return {"preview_id": "missing-preview", "accepted_keywords": []}

    with pytest.raises(HTTPException) as exc_info:
        await app.ingest_run(RequestWithoutSource())

    assert exc_info.value.status_code == 400
    assert "content source" in exc_info.value.detail


@pytest.mark.asyncio
async def test_run_pipeline_requires_a_content_source():
    from pipeline import run_pipeline

    with pytest.raises(ValueError, match="content source is required"):
        async for _ in run_pipeline():
            pass


@pytest.mark.asyncio
async def test_discovery_fetch_propagates_cancellation(monkeypatch):
    from core.discovery_scheduler import DiscoveryScheduler

    scheduler = object.__new__(DiscoveryScheduler)

    def cancelled_request(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr("core.discovery_scheduler.requests.get", cancelled_request)

    with pytest.raises(asyncio.CancelledError):
        await scheduler._fetch_html("https://example.com")


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
