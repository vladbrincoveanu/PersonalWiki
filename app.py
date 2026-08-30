# app.py
import asyncio
import logging
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
from core.discovery_logger import get_discovery_logger as _get_dl_logger
from core.keywords_manager import load_manual_keywords, add_keyword as _add_keyword
from core.doctor_scheduler import DoctorScheduler

_logger = logging.getLogger(__name__)
_job_queues: dict[str, tuple[asyncio.Queue, asyncio.Event]] = {}
_ingest_run_queues: dict[str, tuple[asyncio.Queue, asyncio.Event]] = {}
_preview_cache: dict[str, dict] = {}
_PREVIEW_TTL = 300
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_UPLOAD_CHUNK_SIZE = 1024 * 1024
_scheduler: DiscoveryScheduler | None = None
_doctor_scheduler: DoctorScheduler | None = None
_scheduler_lock = asyncio.Lock()


def _remove_temp_file(path: str | None) -> None:
    """Remove a temporary upload if it still exists."""
    if not path:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


async def _save_upload(file: UploadFile) -> tuple[str, str]:
    """Stream an upload to disk and reject files above the application limit."""
    ext = Path(file.filename.lower()).suffix if file.filename else ""
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    total = 0
    try:
        while True:
            chunk = await file.read(_UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Uploaded file exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit",
                )
            tmp.write(chunk)
    except BaseException:
        tmp.close()
        _remove_temp_file(tmp.name)
        raise
    tmp.close()
    return tmp.name, ext


def _purge_expired_previews(now: float | None = None, *, force: bool = False) -> int:
    """Delete expired preview entries, or all entries when force is true."""
    current_time = time.time() if now is None else now
    removed = 0
    for preview_id, preview in list(_preview_cache.items()):
        if force:
            expired = True
        else:
            try:
                expired = current_time - float(preview.get("created_at", 0)) >= _PREVIEW_TTL
            except (TypeError, ValueError):
                expired = True
        if (force or expired) and _preview_cache.pop(preview_id, None) is not None:
            _remove_temp_file(preview.get("tmp_path"))
            removed += 1
    return removed


def _cleanup_queued_job(
    queues: dict[str, tuple[asyncio.Queue, asyncio.Event]],
    job_id: str,
    tmp_path: str | None,
) -> None:
    """Remove queue and upload resources, including for never-started tasks."""
    queues.pop(job_id, None)
    _remove_temp_file(tmp_path)


def _finalize_job_task(
    task: asyncio.Task,
    queues: dict[str, tuple[asyncio.Queue, asyncio.Event]],
    job_id: str,
    tmp_path: str | None,
) -> None:
    """Clean up a completed job and retrieve unexpected task exceptions."""
    _cleanup_queued_job(queues, job_id, tmp_path)
    if task.cancelled():
        return
    exception = task.exception()
    if exception is not None:
        _logger.error(
            "Background ingest job %s failed",
            job_id,
            exc_info=(type(exception), exception, exception.__traceback__),
        )


async def _preview_cleanup_loop() -> None:
    """Enforce preview TTL even when no new preview request arrives."""
    try:
        while True:
            await asyncio.sleep(_PREVIEW_TTL)
            _purge_expired_previews()
    except asyncio.CancelledError:
        raise


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
    preview_cleanup_task = asyncio.create_task(_preview_cleanup_loop())
    try:
        try:
            count = await asyncio.to_thread(scan_vault)
            if count:
                print(f"Startup: indexed {count} notes.")
        except Exception as e:
            print(f"Startup: scan_vault failed ({e}), starting without vault index.")
        yield
    finally:
        preview_cleanup_task.cancel()
        try:
            await preview_cleanup_task
        except asyncio.CancelledError:
            pass
        _purge_expired_previews(force=True)
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
        try:
            tmp_path, ext = await _save_upload(file)
        except BaseException:
            _job_queues.pop(job_id, None)
            raise

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
            _cleanup_queued_job(_job_queues, job_id, tmp_path)

    run_task = asyncio.create_task(_run())
    # A task cancelled before its first scheduling turn may not enter the
    # coroutine body, so keep cleanup reliable in that edge case too.
    run_task.add_done_callback(
        lambda task: _finalize_job_task(task, _job_queues, job_id, tmp_path)
    )

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
        await scheduler.trigger_cycle()
        return {"status": "triggered"}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/discovery/clear")
async def clear_discovery_activity():
    """Clear all discovery activity events from memory and disk."""
    _get_dl_logger().clear()
    return {"status": "cleared"}


def _guess_title(doc, url: str) -> str:
    """Extract a title from the document or fall back to URL stem."""
    raw = getattr(doc, "raw_text", "") or ""
    for line in raw.split("\n"):
        stripped = line.strip().strip("#").strip()
        if not stripped or len(stripped) < 10:
            continue
        if stripped.startswith("Skip to") or stripped.startswith("[Skip to"):
            continue
        return stripped[:120]
    try:
        from urllib.parse import urlparse
        stem = Path(urlparse(url).path).stem or Path(url).stem
        if stem and stem != "index":
            return stem.replace("-", " ").replace("_", " ").title()[:120]
    except Exception:
        pass
    return "Untitled"


@app.post("/ingest/preview")
async def ingest_preview(
    url: str = Form(None),
    file: UploadFile = None,
):
    """Phase 1: extract content and return keyword classification."""
    _purge_expired_previews()
    if not url and not file:
        raise HTTPException(400, "No url or file provided")

    tmp_path = None
    if file and file.filename:
        tmp_path, ext = await _save_upload(file)

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

        title = _guess_title(doc, url or "")
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
        _remove_temp_file(tmp_path)
        raise
    except asyncio.CancelledError:
        _remove_temp_file(tmp_path)
        raise
    except Exception as e:
        _remove_temp_file(tmp_path)
        raise HTTPException(500, f"Preview failed: {e}")


@app.post("/ingest/run")
async def ingest_run(request: Request):
    """Phase 2: run full pipeline with confirmed keywords."""
    _purge_expired_previews()
    body = await request.json()
    preview_id = body.get("preview_id")
    accepted_keywords = list(body.get("accepted_keywords", []))
    source_url = body.get("url")

    cached = _preview_cache.pop(preview_id, None) if preview_id else None

    if not source_url and not (cached and (cached.get("url") or cached.get("tmp_path"))):
        raise HTTPException(400, "Preview expired or no content source provided")

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
            elif cached and cached.get("tmp_path"):
                tmp = cached["tmp_path"]
                ext = Path(tmp).suffix.lower()
                if ext == ".pdf":
                    kwargs["pdf_path"] = tmp
                elif ext == ".docx":
                    kwargs["docx_path"] = tmp
                elif ext in (".md", ".markdown", ".txt"):
                    kwargs["md_path"] = tmp
                else:
                    await queue.put("<p>Error: Unsupported file type</p>")
                    await queue.put(None)
                    done_event.set()
                    _cleanup_queued_job(_ingest_run_queues, job_id, None)
                    return

            async for msg in run_pipeline(**kwargs):
                await queue.put(f"<p>{msg}</p>")
        except Exception as e:
            await queue.put(f"<p>Error: {e}</p>")
        finally:
            await queue.put(None)
            done_event.set()
            _cleanup_queued_job(
                _ingest_run_queues,
                job_id,
                cached.get("tmp_path") if cached else None,
            )

    run_task = asyncio.create_task(_run())
    run_task.add_done_callback(
        lambda task: _finalize_job_task(
            task,
            _ingest_run_queues,
            job_id,
            cached.get("tmp_path") if cached else None,
        )
    )
    return {"job_id": job_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8100, reload=True)
