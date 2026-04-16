# app.py
import asyncio
import uuid
import tempfile
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Form, UploadFile, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from pipeline import run_pipeline
from vault.scanner import scan_vault
from core.discovery_scheduler import DiscoveryScheduler, KEYWORDS_FILE
from core.keywords_manager import load_manual_keywords

_job_queues: dict[str, tuple[asyncio.Queue, asyncio.Event]] = {}
_scheduler: DiscoveryScheduler | None = None
_scheduler_lock = asyncio.Lock()

async def _get_scheduler() -> DiscoveryScheduler:
    global _scheduler
    if _scheduler is None:
        async with _scheduler_lock:
            # Double-check after acquiring lock
            if _scheduler is None:
                _scheduler = DiscoveryScheduler()
                _scheduler.start(pipeline_func=run_pipeline)
    return _scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        count = await asyncio.to_thread(scan_vault)
        if count:
            print(f"Startup: indexed {count} notes.")
    except Exception as e:
        print(f"Startup: scan_vault failed ({e}), starting without vault index.")
    yield

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.post("/ingest", response_class=HTMLResponse)
async def ingest(
    request: Request,
    url: str = Form(None),
    file: UploadFile = None,
):
    job_id = str(uuid.uuid4())
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    done_event = asyncio.Event()
    _job_queues[job_id] = (queue, done_event)

    async def _run():
        kwargs = {}
        tmp_path = None
        if file and file.filename:
            content = await file.read()
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            kwargs["pdf_path"] = tmp_path
        elif url:
            kwargs["url"] = url

        try:
            async for msg in run_pipeline(**kwargs):
                await queue.put(f"<p>{msg}</p>")
        except Exception as e:
            await queue.put(f"<p>❌ Unexpected error: {e}</p>")
        finally:
            await queue.put(None)  # Sentinel
            done_event.set()  # Signal stream() to exit and allow cleanup
            _job_queues.pop(job_id, None)
            if tmp_path:
                os.unlink(tmp_path)

    asyncio.create_task(_run())

    return HTMLResponse(f"""
        <div id="progress"
             hx-ext="sse"
             sse-connect="/stream/{job_id}"
             sse-swap="message"
             hx-target="#progress"
             hx-swap="beforeend">
            <p>Starting...</p>
        </div>
    """)

@app.get("/stream/{job_id}")
async def stream(job_id: str):
    async def generate():
        entry = _job_queues.get(job_id)
        if not entry:
            return
        queue, done_event = entry
        while True:
            msg = await queue.get()
            if msg is None:
                break
            yield {"event": "message", "data": msg}
    return EventSourceResponse(generate())


@app.get("/keywords")
async def get_keywords():
    """Return the scheduler's keyword list split into manual vs graph-derived."""
    scheduler = await _get_scheduler()
    manual = await asyncio.to_thread(load_manual_keywords, KEYWORDS_FILE)
    manual_set = set(manual)
    graph = [kw for kw in scheduler._keywords if kw not in manual_set]
    return {
        "keywords": scheduler._keywords,
        "manual": manual,
        "graph": graph,
        "total": len(scheduler._keywords),
    }


@app.post("/keywords/add")
async def add_keyword(keyword: str = Form(...)):
    """Add a manual keyword to .interests."""
    scheduler = await _get_scheduler()
    try:
        scheduler.add_keyword(keyword)
    except ValueError:
        raise HTTPException(status_code=409, detail=f"Keyword '{keyword}' already exists")
    return {"added": keyword}


@app.post("/keywords/remove")
async def remove_keyword(keyword: str = Form(...)):
    """Remove a manual keyword from _keywords and purge related files."""
    scheduler = await _get_scheduler()
    try:
        purged = scheduler.remove_keyword(keyword)
    except (KeyError, ValueError):
        raise HTTPException(status_code=404, detail=f"Keyword '{keyword}' not found")
    return {"removed": keyword, "purged": purged, "purged_count": len(purged)}


@app.post("/keywords/suppress")
async def suppress_keyword(keyword: str = Form(...)):
    """Suppress a graph keyword: block it from discovery and purge related files."""
    scheduler = await _get_scheduler()
    purged = scheduler.suppress_keyword(keyword)
    return {"suppressed": keyword, "purged": purged, "purged_count": len(purged)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
