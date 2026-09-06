import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.bm25_index import BM25Index
from core.discovery_scheduler import DiscoveryScheduler
from core.keyword_extractor import KeywordExtractor
from core.keywords_manager import KeywordsManager
from core.mcp_server import mcp
from core.vector_store import VectorStore
from ingesters.router import route_and_ingest
from pipeline import Pipeline
from vault.doctor import DoctorScheduler
from vault.writer import VaultWriter

# Observability imports
try:
    from observability import init_observability, shutdown_observability, get_tracer
    OBSERVABILITY_AVAILABLE = True
except ImportError:
    OBSERVABILITY_AVAILABLE = False

_logger = logging.getLogger(__name__)
_job_queues: dict[str, tuple[asyncio.Queue, asyncio.Event]] = {}
_ingest_run_queues: dict[str, tuple[asyncio.Queue, asyncio.Event]] = {}
_preview_cache: dict[str, dict] = {}

# Global instances
_pipeline: Pipeline | None = None
_vector_store: VectorStore | None = None
_bm25_index: BM25Index | None = None
_keyword_extractor: KeywordExtractor | None = None
_keywords_manager: KeywordsManager | None = None
_vault_writer: VaultWriter | None = None
_doctor_scheduler: DoctorScheduler | None = None
_discovery_scheduler: DiscoveryScheduler | None = None
_preview_cleanup_task: asyncio.Task | None = None


def _purge_expired_previews(force: bool = False) -> None:
    """Purge expired preview cache entries."""
    import time
    now = time.time()
    expired = [k for k, v in _preview_cache.items() if force or now - v.get("timestamp", 0) > 3600]
    for k in expired:
        _preview_cache.pop(k, None)
    if expired:
        _logger.info("Purged %d expired preview cache entries", len(expired))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipeline, _vector_store, _bm25_index, _keyword_extractor, _keywords_manager
    global _vault_writer, _doctor_scheduler, _discovery_scheduler, _preview_cleanup_task

    # Initialize observability
    if OBSERVABILITY_AVAILABLE:
        init_observability()

    # Initialize core components
    _vector_store = VectorStore()
    _bm25_index = BM25Index()
    _keyword_extractor = KeywordExtractor()
    _keywords_manager = KeywordsManager()
    _vault_writer = VaultWriter()
    _pipeline = Pipeline(
        vector_store=_vector_store,
        bm25_index=_bm25_index,
        keyword_extractor=_keyword_extractor,
        keywords_manager=_keywords_manager,
        vault_writer=_vault_writer,
    )

    # Start background tasks
    _doctor_scheduler = DoctorScheduler(_vault_writer)
    _doctor_scheduler.start()

    _discovery_scheduler = DiscoveryScheduler(_pipeline, _keywords_manager)
    _discovery_scheduler.start()

    # Start preview cleanup task
    async def preview_cleanup_loop():
        while True:
            await asyncio.sleep(300)  # 5 minutes
            _purge_expired_previews()

    _preview_cleanup_task = asyncio.create_task(preview_cleanup_loop())

    yield

    # Shutdown
    if _preview_cleanup_task:
        _preview_cleanup_task.cancel()
        try:
            await _preview_cleanup_task
        except asyncio.CancelledError:
            pass
    _purge_expired_previews(force=True)
    if _doctor_scheduler:
        _doctor_scheduler.stop()
    if OBSERVABILITY_AVAILABLE:
        shutdown_observability()


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include MCP server
app.include_router(mcp.http_router(), prefix="/mcp")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/ingest")
async def ingest(request: Request):
    body = await request.json()
    url = body.get("url")
    type_ = body.get("type", "auto")
    domain = body.get("domain")
    if not url:
        return {"error": "url is required"}, 400
    job_id = await route_and_ingest(_pipeline, url, type_, domain)
    return {"job_id": job_id}


@app.get("/ingest/{job_id}")
async def ingest_status(job_id: str):
    queue, event = _job_queues.get(job_id, (None, None))
    if queue is None:
        return {"error": "job not found"}, 404
    try:
        result = queue.get_nowait()
        return result
    except asyncio.QueueEmpty:
        return {"status": "pending"}


@app.post("/ingest/run")
async def ingest_run(request: Request):
    body = await request.json()
    urls = body.get("urls", [])
    type_ = body.get("type", "auto")
    domain = body.get("domain")
    if not urls:
        return {"error": "urls is required"}, 400
    run_id = f"run_{len(_ingest_run_queues)}"
    queue, event = asyncio.Queue(), asyncio.Event()
    _ingest_run_queues[run_id] = (queue, event)
    asyncio.create_task(_run_ingest_batch(run_id, urls, type_, domain))
    return {"run_id": run_id}


async def _run_ingest_batch(run_id: str, urls: list[str], type_: str, domain: str | None):
    queue, event = _ingest_run_queues[run_id]
    results = []
    for url in urls:
        try:
            job_id = await route_and_ingest(_pipeline, url, type_, domain)
            results.append({"url": url, "job_id": job_id, "status": "started"})
        except Exception as e:
            results.append({"url": url, "error": str(e), "status": "failed"})
    await queue.put({"run_id": run_id, "results": results, "status": "completed"})
    event.set()


@app.get("/ingest/run/{run_id}")
async def ingest_run_status(run_id: str):
    queue, event = _ingest_run_queues.get(run_id, (None, None))
    if queue is None:
        return {"error": "run not found"}, 404
    try:
        result = queue.get_nowait()
        return result
    except asyncio.QueueEmpty:
        return {"status": "pending"}


@app.get("/search")
async def search(q: str, limit: int = 10, mode: str = "hybrid"):
    if not _pipeline:
        return {"error": "pipeline not initialized"}, 500
    results = await _pipeline.search(q, limit=limit, mode=mode)
    return {"results": results}


@app.get("/keywords")
async def get_keywords():
    if not _keywords_manager:
        return {"error": "keywords manager not initialized"}, 500
    return {"keywords": _keywords_manager.get_all()}


@app.post("/keywords")
async def add_keyword(request: Request):
    body = await request.json()
    keyword = body.get("keyword")
    if not keyword:
        return {"error": "keyword is required"}, 400
    if not _keywords_manager:
        return {"error": "keywords manager not initialized"}, 500
    _keywords_manager.add(keyword)
    return {"status": "added"}


@app.delete("/keywords/{keyword}")
async def remove_keyword(keyword: str):
    if not _keywords_manager:
        return {"error": "keywords manager not initialized"}, 500
    _keywords_manager.remove(keyword)
    return {"status": "removed"}


@app.post("/discover")
async def discover(request: Request):
    body = await request.json()
    seed_urls = body.get("seed_urls", [])
    max_depth = body.get("max_depth", 2)
    if not seed_urls:
        return {"error": "seed_urls is required"}, 400
    if not _discovery_scheduler:
        return {"error": "discovery scheduler not initialized"}, 500
    job_id = await _discovery_scheduler.schedule_discovery(seed_urls, max_depth)
    return {"job_id": job_id}


@app.get("/vault/stats")
async def vault_stats():
    if not _vault_writer:
        return {"error": "vault writer not initialized"}, 500
    return _vault_writer.get_stats()


@app.post("/vault/doctor")
async def vault_doctor(request: Request):
    body = await request.json()
    fix = body.get("fix", False)
    if not _vault_writer:
        return {"error": "vault writer not initialized"}, 500
    result = await _vault_writer.doctor(fix=fix)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
