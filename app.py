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
from core.discovery_scheduler import DiscoveryScheduler

_job_queues: dict[str, asyncio.Queue] = {}
_scheduler: DiscoveryScheduler | None = None

def _get_scheduler() -> DiscoveryScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = DiscoveryScheduler()
        _scheduler.start(pipeline_func=run_pipeline)
    return _scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    count = await asyncio.to_thread(scan_vault)
    if count:
        print(f"Startup: indexed {count} notes.")
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
    _job_queues[job_id] = asyncio.Queue()

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
                await _job_queues[job_id].put(f"<p>{msg}</p>")
        except Exception as e:
            await _job_queues[job_id].put(f"<p>❌ Unexpected error: {e}</p>")
        finally:
            if tmp_path:
                os.unlink(tmp_path)
            await _job_queues[job_id].put(None)

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
        q = _job_queues.get(job_id)
        if not q:
            return
        while True:
            msg = await q.get()
            if msg is None:
                _job_queues.pop(job_id, None)
                break
            yield {"event": "message", "data": msg}
    return EventSourceResponse(generate())


@app.get("/keywords")
async def get_keywords():
    """Return the scheduler's pre-loaded merged keyword list."""
    scheduler = _get_scheduler()
    return {
        "keywords": scheduler._keywords,
        "manual": [],  # not needed for display
        "graph": [],   # not needed for display
        "total": len(scheduler._keywords),
    }


@app.post("/keywords/add")
async def add_keyword(keyword: str = Form(...)):
    """Add a manual keyword to .interests."""
    scheduler = _get_scheduler()
    try:
        scheduler.add_keyword(keyword)
    except ValueError:
        raise HTTPException(status_code=409, detail=f"Keyword '{keyword}' already exists")
    return {"added": keyword}


@app.post("/keywords/remove")
async def remove_keyword(keyword: str = Form(...)):
    """Remove a manual keyword from _keywords and purge related files."""
    scheduler = _get_scheduler()
    try:
        purged = scheduler.remove_keyword(keyword)
    except (KeyError, ValueError):
        raise HTTPException(status_code=404, detail=f"Keyword '{keyword}' not found")
    return {"removed": keyword, "purged": purged, "purged_count": len(purged)}


@app.post("/keywords/suppress")
async def suppress_keyword(keyword: str = Form(...)):
    """Suppress a graph keyword: block it from discovery and purge related files."""
    scheduler = _get_scheduler()
    purged = scheduler.suppress_keyword(keyword)
    return {"suppressed": keyword, "purged": purged, "purged_count": len(purged)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
