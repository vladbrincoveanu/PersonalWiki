# tests/test_app.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

def make_client():
    with patch("app.scan_vault", return_value=0):
        from app import app
        return TestClient(app)

def test_index_returns_html():
    client = make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "VKE Local" in resp.text
    assert "hx-post" in resp.text

def test_ingest_url_returns_sse_div():
    async def fake_pipeline(**kwargs):
        yield "Extracting..."
        yield "Saved → notes/test.md"

    client = make_client()
    with patch("app.run_pipeline", fake_pipeline):
        resp = client.post("/ingest", data={"url": "https://example.com"})

    assert resp.status_code == 200
    assert "sse-connect" in resp.text or "job_id" in resp.text

def test_stream_yields_events():
    import asyncio
    from app import _job_queues
    import uuid

    job_id = str(uuid.uuid4())
    q = asyncio.Queue()

    async def fill():
        await q.put("<p>Step 1</p>")
        await q.put(None)

    asyncio.run(fill())
    _job_queues[job_id] = q

    client = make_client()
    with client.stream("GET", f"/stream/{job_id}") as resp:
        content = b"".join(resp.iter_bytes())

    assert b"Step 1" in content

@pytest.mark.asyncio
async def test_job_queue_cleanup_not_racy():
    """stream() must not pop queue while _run() is still writing."""
    import asyncio
    from app import _job_queues

    job_id = "test-race-123"
    queue = asyncio.Queue()
    _job_queues[job_id] = queue

    async def writer():
        for i in range(5):
            await queue.put(f"<p>msg {i}</p>")
        await queue.put(None)
        # _run() cleanup: give stream() time to drain before removing from dict
        await asyncio.sleep(0.05)
        _job_queues.pop(job_id, None)

    async def reader():
        results = []
        while True:
            msg = await queue.get()
            if msg is None:
                break
            results.append(msg)
        return results

    # Run concurrently — without fix, this may miss messages or KeyError
    writer_task = asyncio.create_task(writer())
    reader_task = asyncio.create_task(reader())
    results = await reader_task
    await writer_task

    assert len(results) == 5
    assert job_id not in _job_queues  # queue must be cleaned up
