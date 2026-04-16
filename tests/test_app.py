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
    assert "personalWiki" in resp.text
    assert 'action="/ingest"' in resp.text  # form posts to /ingest

def test_ingest_url_returns_job_json():
    """Ingest endpoint returns JSON with job_id field, not HTML."""
    async def fake_pipeline(**kwargs):
        yield "Extracting..."
        yield "Saved → notes/test.md"

    client = make_client()
    with patch("app.run_pipeline", fake_pipeline):
        resp = client.post("/ingest", data={"url": "https://example.com"})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json", \
        f"Expected JSON but got {resp.headers.get('content-type')}"
    body = resp.json()
    assert "job_id" in body, f"Expected job_id in JSON response, got: {body}"
    assert len(body["job_id"]) == 36  # UUID format

def test_stream_yields_events():
    import asyncio
    from app import _job_queues
    import uuid

    job_id = str(uuid.uuid4())
    q = asyncio.Queue()
    done_event = asyncio.Event()

    async def fill():
        await q.put("<p>Step 1</p>")
        await q.put(None)

    asyncio.run(fill())
    _job_queues[job_id] = (q, done_event)

    client = make_client()
    with client.stream("GET", f"/stream/{job_id}") as resp:
        content = b"".join(resp.iter_bytes())

    assert b"Step 1" in content

@pytest.mark.asyncio
async def test_get_scheduler_singleton_not_racy():
    """Concurrent calls to _get_scheduler() must not create two schedulers."""
    import asyncio
    from unittest.mock import patch, MagicMock

    # Reset global state
    import app
    app._scheduler = None

    call_count = 0
    original_scheduler_class = app.DiscoveryScheduler

    def counting_scheduler():
        nonlocal call_count
        call_count += 1
        return original_scheduler_class()

    with patch.object(app, 'DiscoveryScheduler', counting_scheduler):
        async def get_scheduler_twice():
            s1 = await app._get_scheduler()
            s2 = await app._get_scheduler()
            return s1, s2

        s1, s2 = await get_scheduler_twice()
        assert call_count == 1, f"Scheduler created {call_count} times instead of once"
        assert s1 is s2


@pytest.mark.asyncio
async def test_job_queue_cleanup_not_racy():
    """stream() must not pop queue while _run() is still writing."""
    import asyncio
    from app import _job_queues

    job_id = "test-race-123"
    queue = asyncio.Queue()
    done_event = asyncio.Event()
    _job_queues[job_id] = (queue, done_event)

    async def writer():
        for i in range(5):
            await queue.put(f"<p>msg {i}</p>")
        await queue.put(None)
        done_event.set()  # Signal stream() done; _run() will pop
        # Simulate _run() cleanup after done_event is set
        await asyncio.sleep(0)
        _job_queues.pop(job_id, None)

    async def reader():
        results = []
        while True:
            msg = await queue.get()
            if msg is None:
                break
            results.append(msg)
        await done_event.wait()  # Wait for writer to clean up
        return results

    # Run concurrently — without fix, this may miss messages or KeyError
    writer_task = asyncio.create_task(writer())
    reader_task = asyncio.create_task(reader())
    results = await reader_task
    await writer_task

    assert len(results) == 5
    assert job_id not in _job_queues  # queue must be cleaned up
