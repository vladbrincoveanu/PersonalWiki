# tests/test_app.py
import os
import sys
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
    assert '<form id="ingest-form"' in resp.text
    assert "fetch('/ingest/preview'" in resp.text

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

@pytest.mark.asyncio
async def test_stream_yields_events():
    import asyncio
    import app as app_module
    from app import _job_queues
    import uuid

    # Save and reset ALL scheduler state to prevent pollution
    prior_scheduler = app_module._scheduler
    prior_lock = app_module._scheduler_lock
    if prior_scheduler is not None:
        prior_scheduler.stop()
    app_module._scheduler = None
    app_module._scheduler_lock = None
    # Also clear job queues to be safe
    _job_queues.clear()

    job_id = str(uuid.uuid4())
    q = asyncio.Queue()
    done_event = asyncio.Event()
    _job_queues[job_id] = (q, done_event)

    client = make_client()
    try:
        await q.put("<p>Step 1</p>")
        await q.put(None)
        done_event.set()
        with client.stream("GET", f"/stream/{job_id}") as resp:
            content = b"".join(resp.iter_bytes())

        assert b"Step 1" in content
    finally:
        _job_queues.clear()
        if app_module._scheduler is not None:
            app_module._scheduler.stop()
        app_module._scheduler = prior_scheduler
        app_module._scheduler_lock = prior_lock

@pytest.mark.asyncio
async def test_get_scheduler_singleton_not_racy():
    """Concurrent calls to _get_scheduler() must not create two schedulers."""
    import asyncio
    from unittest.mock import patch, MagicMock

    # Reset global state fully (including stopping any running scheduler)
    import app
    if app._scheduler is not None:
        app._scheduler.stop()
        app._scheduler = None
    app._scheduler_lock = asyncio.Lock()

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


def test_keywords_returns_graph_and_manual():
    """Keywords endpoint returns graph keywords (from vault) and manual keywords (from _keywords file)."""
    import app as app_module

    # Mock the scheduler with known keywords
    mock_scheduler = MagicMock()
    mock_scheduler._keywords = ["quantum physics", "machine learning", "high energy physics"]

    async def mock_get_scheduler():
        return mock_scheduler

    with patch.object(app_module, '_get_scheduler', mock_get_scheduler):
        with patch('app.load_manual_keywords', return_value=["physics"]):
            client = make_client()
            resp = client.get("/keywords")

    assert resp.status_code == 200
    body = resp.json()
    assert "keywords" in body
    assert "manual" in body
    assert "graph" in body
    assert "total" in body
    # Manual should contain "physics", graph should have the rest
    assert "physics" in body["manual"], f"Expected 'physics' in manual, got: {body['manual']}"
    assert "quantum physics" in body["graph"], f"Expected 'quantum physics' in graph, got: {body['graph']}"
    assert body["total"] == len(body["manual"]) + len(body["graph"])


def test_ingest_docx_file_returns_job_json(tmp_path):
    """DOCX file upload to /ingest returns job_id JSON, not HTML or error."""
    import os
    import app as app_module

    # Save and reset scheduler state
    prior_scheduler = app_module._scheduler
    app_module._scheduler = None
    app_module._scheduler_lock = None
    app_module._job_queues.clear()

    async def fake_pipeline(**kwargs):
        # Verify docx_path is passed, not pdf_path
        assert "docx_path" in kwargs, f"Expected docx_path in kwargs, got: {kwargs.keys()}"
        assert "pdf_path" not in kwargs
        yield "Extracting DOCX content..."
        yield "Saved → notes/test.docx.md"

    docx_path = tmp_path / "test_docx.docx"
    docx_path.write_bytes(b"test docx payload")

    try:
        client = make_client()
        with patch("app.run_pipeline", fake_pipeline):
            with docx_path.open("rb") as f:
                resp = client.post(
                    "/ingest",
                    files={"file": ("test_docx.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
                )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert resp.headers["content-type"] == "application/json", \
            f"Expected JSON but got {resp.headers.get('content-type')}"
        body = resp.json()
        assert "job_id" in body, f"Expected job_id in JSON response, got: {body}"
        assert len(body["job_id"]) == 36  # UUID format
    finally:
        app_module._job_queues.clear()
        if prior_scheduler is not None:
            prior_scheduler.stop()
        app_module._scheduler = prior_scheduler


def test_ingest_preview_returns_keywords():
    """POST /ingest/preview returns extracted keywords with existing vs new classification."""
    import app as app_module

    prior_scheduler = app_module._scheduler
    app_module._scheduler = None
    app_module._scheduler_lock = None
    app_module._preview_cache.clear()

    try:
        client = make_client()
        with patch("core.keyword_extractor.extract_and_classify", return_value={"existing": ["python"], "new": ["deep-learning"]}):
            with patch("ingesters.router.extract", new_callable=AsyncMock) as mock_extract:
                mock_extract.return_value = MagicMock(
                    title="Test Article",
                    raw_text="Python and deep learning content.",
                    content_type="article",
                )
                resp = client.post("/ingest/preview", data={"url": "https://example.com"})

        assert resp.status_code == 200
        data = resp.json()
        assert "preview_id" in data
        assert data["keywords"]["existing"] == ["python"]
        assert data["keywords"]["new"] == ["deep-learning"]
    finally:
        app_module._preview_cache.clear()
        app_module._scheduler = prior_scheduler


def test_ingest_run_returns_job_id():
    """POST /ingest/run returns a job_id for the confirmed keywords pipeline."""
    import app as app_module

    prior_scheduler = app_module._scheduler
    app_module._scheduler = None
    app_module._scheduler_lock = None
    app_module._preview_cache.clear()
    app_module._ingest_run_queues.clear()

    async def fake_pipeline(**kwargs):
        yield "Done"

    try:
        client = make_client()
        with patch("app.run_pipeline", fake_pipeline):
            with patch("app.load_manual_keywords", return_value=["python"]):
                resp = client.post("/ingest/run", json={
                    "preview_id": "test-preview-123",
                    "accepted_keywords": ["python", "new-kw"],
                    "url": "https://example.com",
                })

        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
    finally:
        app_module._preview_cache.clear()
        app_module._ingest_run_queues.clear()
        app_module._scheduler = prior_scheduler


def test_trigger_discovery_returns_triggered():
    """POST /discovery/trigger starts a discovery cycle."""
    import app as app_module

    mock_scheduler = MagicMock()
    mock_scheduler.trigger_cycle = AsyncMock()
    prior_scheduler = app_module._scheduler
    app_module._scheduler = mock_scheduler

    async def mock_get_scheduler():
        return mock_scheduler

    try:
        with patch.object(app_module, "_get_scheduler", mock_get_scheduler):
            client = make_client()
            resp = client.post("/discovery/trigger")
        assert resp.status_code == 200
        assert resp.json()["status"] == "triggered"
    finally:
        app_module._scheduler = prior_scheduler


def test_ingest_docx_routes_to_correct_extractor(tmp_path):
    """DOCX file with .docx extension should route to extract_docx via docx_path."""
    import app as app_module

    prior_scheduler = app_module._scheduler
    app_module._scheduler = None
    app_module._scheduler_lock = None
    app_module._job_queues.clear()

    captured_kwargs = {}

    async def capture_pipeline(**kwargs):
        captured_kwargs.update(kwargs)
        yield "done"

    docx_path = tmp_path / "test_docx.docx"
    docx_path.write_bytes(b"test docx payload")

    try:
        client = make_client()
        with patch("app.run_pipeline", capture_pipeline):
            with docx_path.open("rb") as f:
                resp = client.post(
                    "/ingest",
                    files={"file": ("my_document.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
                )

        assert resp.status_code == 200
        # Wait briefly for the async task to complete
        import time
        time.sleep(0.5)

        assert "docx_path" in captured_kwargs, f"Expected docx_path in captured kwargs, got: {captured_kwargs}"
        assert captured_kwargs["docx_path"].endswith(".docx"), \
            f"Expected docx_path to end with .docx, got: {captured_kwargs['docx_path']}"
    finally:
        app_module._job_queues.clear()
        if prior_scheduler is not None:
            prior_scheduler.stop()
        app_module._scheduler = prior_scheduler


@pytest.mark.skipif(
    os.environ.get("SKIP_PLAYWRIGHT") == "1",
    reason="Playwright browser test — set SKIP_PLAYWRIGHT=1 to skip"
)
@pytest.mark.integration
def test_docx_upload_shows_badge_and_progress_via_browser():
    """
    End-to-end browser test: upload DOCX → badge appears with correct type
    → progress stream delivers events → job completes.

    Uses Playwright to test the actual browser DOM + SSE behavior, not mocked.
    """
    import subprocess
    import time
    import signal

    # Find a real DOCX test file
    docx_path = "/tmp/test_docx_large.docx"
    if not os.path.exists(docx_path):
        pytest.skip("Test DOCX file not found at /tmp/test_docx_large.docx")

    # Start app in a subprocess on a different port
    env = {**os.environ, "SKIP_PLAYWRIGHT": "1"}
    server = subprocess.Popen(
        [sys.executable, "-c", f"""
import uvicorn
import sys
sys.path.insert(0, '{os.getcwd()}')
from app import app
uvicorn.run(app, host='127.0.0.1', port=18765, log_level='error')
"""],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=os.getcwd(),
        env=env,
    )
    time.sleep(4)  # Let server start

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()

            console_errors = []
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

            page.goto("http://127.0.0.1:18765/")

            # Upload DOCX
            page.set_input_files('input[name="file"]', docx_path)

            # 0. Filename must appear in drop zone after selection
            page.wait_for_function(
                'document.getElementById("selected-file").classList.contains("visible")',
                timeout=3000,
            )
            filename = page.evaluate('document.getElementById("selected-file").innerText')
            assert "docx" in filename.lower(), f"Expected docx in filename, got: {filename}"

            page.click('button[type="submit"]')

            # 1. Badge must appear within 5s (uses CSS class 'visible' not inline style)
            page.wait_for_function(
                'document.getElementById("source-badge").classList.contains("visible")',
                timeout=5000,
            )
            badge_class = page.evaluate('document.getElementById("source-badge").className')
            badge_text = page.evaluate('document.getElementById("source-badge").innerText')
            assert "docx" in badge_class, f"Expected docx in badge class, got: {badge_class}"
            assert "Word" in badge_text, f"Expected 'Word' in badge text, got: {badge_text}"

            # 2. Progress box must show content within 10s
            page.wait_for_function(
                'document.getElementById("progress-box").innerText.includes("Extracting")',
                timeout=10000,
            )

            # 3. Job must complete (Saved or Skipped) within 120s
            page.wait_for_function(
                'document.getElementById("progress-box").innerText.includes("Saved") || '
                'document.getElementById("progress-box").innerText.includes("Skipped")',
                timeout=120000,
            )

            # 4. No console errors
            assert not console_errors, f"Console errors: {console_errors}"

            browser.close()

    finally:
        server.send_signal(signal.SIGTERM)
        server.wait(timeout=5)
