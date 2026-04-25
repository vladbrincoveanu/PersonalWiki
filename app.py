# app.py
import asyncio
import json
import time
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
from core.keywords_manager import load_manual_keywords, add_keyword as _add_keyword
from core.doctor_scheduler import DoctorScheduler

_job_queues: dict[str, tuple[asyncio.Queue, asyncio.Event]] = {}
_ingest_run_queues: dict[str, tuple[asyncio.Queue, asyncio.Event]] = {}
_preview_cache: dict[str, dict] = {}
_PREVIEW_TTL = 300
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
        entry = _job_queues.get(job_id) or _ingest_run_queues.get(job_id)
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
        result = scheduler.remove_keyword(keyword)
    except (KeyError, ValueError):
        raise HTTPException(status_code=404, detail=f"Keyword '{keyword}' not found")
    return {"removed": keyword, "deleted": result["deleted"], "stripped": result["stripped"], "total_deleted": len(result["deleted"]), "total_stripped": len(result["stripped"])}


@app.get("/api/discovery/activity")
async def get_discovery_activity():
    """Return today's discovery activity: stats and events."""
    from core.discovery_logger import get_discovery_logger
    logger = get_discovery_logger()
    return {
        "stats": logger.stats(),
        "events": [dict(e) for e in logger.today()],
    }


@app.post("/discovery/trigger")
async def trigger_discovery():
    """Trigger one discovery cycle immediately."""
    scheduler = await _get_scheduler()
    try:
        asyncio.create_task(scheduler.trigger_cycle())
        return {"status": "triggered"}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/ingest/preview")
async def ingest_preview(
    url: str = Form(None),
    file: UploadFile = None,
):
    """Phase 1: extract content and return keyword classification."""
    if not url and not file:
        raise HTTPException(400, "No url or file provided")

    tmp_path = None
    if file and file.filename:
        content = await file.read()
        ext = Path(file.filename.lower()).suffix
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

    try:
        if url:
            from ingesters.router import extract
            doc = await extract(url)
        elif tmp_path:
            from ingesters.router import extract_pdf, extract_docx, extract_markdown
            if ext == ".pdf":
                doc = await asyncio.to_thread(extract_pdf, tmp_path)
            elif ext == ".docx":
                doc = await asyncio.to_thread(extract_docx, tmp_path)
            else:
                doc = await asyncio.to_thread(extract_markdown, tmp_path)
        else:
            raise HTTPException(400, "No url or file provided")

        title = doc.title or Path(url or "").stem or "Untitled"
        raw_text = doc.raw_text

        from core.keyword_extractor import extract_and_classify
        keywords = await asyncio.to_thread(
            extract_and_classify, raw_text, title, KEYWORDS_FILE
        )

        preview_id = str(uuid.uuid4())
        _preview_cache[preview_id] = {
            "url": url,
            "tmp_path": tmp_path,
            "source": url or tmp_path or "",
            "created_at": time.time(),
        }

        return {
            "preview_id": preview_id,
            "title": title,
            "keywords": keywords,
        }
    except HTTPException:
        raise
    except Exception as e:
        if tmp_path:
            os.unlink(tmp_path)
        raise HTTPException(500, f"Preview failed: {e}")


@app.post("/ingest/run")
async def ingest_run(request: Request):
    """Phase 2: run full pipeline with confirmed keywords."""
    body = await request.json()
    preview_id = body.get("preview_id")
    accepted_keywords = list(body.get("accepted_keywords", []))
    source_url = body.get("url")

    cached = _preview_cache.pop(preview_id, None) if preview_id else None

    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    done_event = asyncio.Event()
    _ingest_run_queues[job_id] = (queue, done_event)

    existing_keywords = await asyncio.to_thread(
        load_manual_keywords, KEYWORDS_FILE
    )

    async def _run():
        try:
            for kw in accepted_keywords:
                if kw not in existing_keywords:
                    try:
                        _add_keyword(kw, KEYWORDS_FILE)
                        await queue.put(f"<p>Keyword added: {kw}</p>")
                    except ValueError:
                        pass

            kwargs = {"keywords": accepted_keywords}
            if cached and cached.get("url"):
                kwargs["url"] = cached["url"]
            elif source_url:
                kwargs["url"] = source_url

            async for msg in run_pipeline(**kwargs):
                await queue.put(f"<p>{msg}</p>")
        except Exception as e:
            await queue.put(f"<p>Error: {e}</p>")
        finally:
            await queue.put(None)
            done_event.set()
            _ingest_run_queues.pop(job_id, None)
            if cached and cached.get("tmp_path"):
                os.unlink(cached["tmp_path"])

    asyncio.create_task(_run())
    return {"job_id": job_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
