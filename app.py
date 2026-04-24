# app.py
import asyncio
import uuid
import tempfile
import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Form, UploadFile, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from pipeline import run_pipeline
from vault.scanner import scan_vault
from core.discovery_scheduler import DiscoveryScheduler, KEYWORDS_FILE
from core.keywords_manager import load_manual_keywords
from core.doctor_scheduler import DoctorScheduler

_job_queues: dict[str, tuple[asyncio.Queue, asyncio.Event]] = {}
_scheduler: DiscoveryScheduler | None = None
_doctor_scheduler: DoctorScheduler | None = None
_scheduler_lock = asyncio.Lock()

async def _get_scheduler() -> DiscoveryScheduler:
    global _scheduler
    if _scheduler is None:
        async with _scheduler_lock:
            # Double-check after acquiring lock
            if _scheduler is None:
                _scheduler = DiscoveryScheduler()
                await _scheduler.start(pipeline_func=run_pipeline)
        # Start daily doctor cron (only once, after scheduler is initialized)
        global _doctor_scheduler
        _doctor_scheduler = DoctorScheduler(interval_hours=24)
        _doctor_scheduler.start(_scheduler)
    return _scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        try:
            count = await asyncio.to_thread(scan_vault)
            if count:
                print(f"Startup: indexed {count} notes.")
        except Exception as e:
            print(f"Startup: scan_vault failed ({e}), starting without vault index.")
        yield
    finally:
        if _doctor_scheduler:
            _doctor_scheduler.stop()

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.post("/ingest")
async def ingest(
    request: Request,
    url: str = Form(None),
    file: UploadFile = None,
):
    job_id = str(uuid.uuid4())
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    done_event = asyncio.Event()
    _job_queues[job_id] = (queue, done_event)

    tmp_path = None
    if file and file.filename:
        content = await file.read()
        ext = Path(file.filename.lower()).suffix
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

    async def _run():
        kwargs = {}
        try:
            if tmp_path:
                if ext == ".pdf":
                    kwargs["pdf_path"] = tmp_path
                elif ext == ".docx":
                    kwargs["docx_path"] = tmp_path
                elif ext == ".md":
                    kwargs["md_path"] = tmp_path
                elif ext == ".txt":
                    kwargs["txt_path"] = tmp_path
                else:
                    await queue.put(f"<p>Error: Unsupported file type {ext}</p>")
                    await queue.put(None)
                    done_event.set()
                    return
            elif url:
                kwargs["url"] = url
            else:
                await queue.put("<p>Error: No url or file.</p>")
                await queue.put(None)
                done_event.set()
                return

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

    return {"job_id": job_id}

@app.get("/stream/{job_id}")
async def stream(job_id: str):
    async def generate():
        entry = _job_queues.get(job_id)
        if not entry:
            return
        queue, done_event = entry
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                if done_event.is_set():
                    break
                yield {"event": "message", "data": "ping - still processing..."}
                continue
            if msg is None:
                yield {"event": "message", "data": "[FINAL]"}
                break
            yield {"event": "message", "data": msg}
    return EventSourceResponse(generate())


@app.get("/note/{slug}")
async def get_note(slug: str):
    """Return the markdown content of a saved note."""
    from config import VAULT_PATH
    note_path = Path(VAULT_PATH) / "notes" / f"{slug}.md"
    if not note_path.exists():
        raise HTTPException(404, "Note not found")
    return {"content": note_path.read_text()}


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
        "total": len(manual) + len(graph),
    }


@app.post("/keywords/add")
async def add_keyword(request: Request):
    """Add a manual keyword to .interests."""
    body = await request.json()
    keyword = body.get("keyword", "")
    scheduler = await _get_scheduler()
    try:
        scheduler.add_keyword(keyword)
    except ValueError:
        raise HTTPException(status_code=409, detail=f"Keyword '{keyword}' already exists")
    return {"added": keyword}


@app.post("/keywords/remove")
async def remove_keyword(request: Request):
    """Remove a manual keyword from _keywords and purge related files."""
    body = await request.json()
    keyword = body.get("keyword", "")
    scheduler = await _get_scheduler()
    try:
        purged = scheduler.remove_keyword(keyword)
    except (KeyError, ValueError):
        raise HTTPException(status_code=404, detail=f"Keyword '{keyword}' not found")
    return {"removed": keyword, "purged": purged, "purged_count": len(purged)}


@app.get("/api/discovery/activity")
async def get_discovery_activity():
    """Return today's discovery activity: stats and events."""
    from core.discovery_logger import get_discovery_logger
    logger = get_discovery_logger()
    return {
        "stats": logger.stats(),
        "events": [dict(e) for e in logger.today()],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
