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
