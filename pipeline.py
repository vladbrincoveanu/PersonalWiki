import asyncio
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import AsyncGenerator
from config import TOP_K_SIMILAR, MAX_EMBED_CHARS
from core.embeddings import embed
from core.vector_store import get_store
from core.minimax_client import enrich
from core.gap_detector import detect_gaps
from ingesters.router import extract, extract_pdf
from vault.writer import write_note
from vault.entity_status import fetch_entity_status


def _is_pdf_url(url: str) -> bool:
    """Return True if the URL serves a PDF (by extension or Content-Type)."""
    if url.lower().split("?")[0].endswith(".pdf"):
        return True
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as resp:
            ct = resp.headers.get("Content-Type", "")
            return "application/pdf" in ct
    except Exception:
        return False


async def _run_gap_searches(gap_entities: list[str]):
    """
    Submit one-shot searches for each gap entity and trigger pipeline
    for the top result. Best-effort — failures are logged and silently ignored.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        from core.discovery_scheduler import DiscoveryScheduler
    except Exception as e:
        logger.warning("Cannot import DiscoveryScheduler for gap search: %s", e)
        return

    try:
        scheduler = DiscoveryScheduler()
        for entity in gap_entities[:5]:
            results = await scheduler._search_keyword(entity)
            for result in results[:1]:
                url = result.get("url")
                if url:
                    await _run_gap_search_pipeline(url)
    except Exception as e:
        logger.debug("Gap search failed (best-effort): %s", e)


async def _run_gap_search_pipeline(url: str):
    """Run ingestion pipeline for a gap search result URL."""
    try:
        async for _ in run_pipeline(url=url):
            pass
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Gap search pipeline failed for %s: %s", url, e)


async def run_pipeline(
    url: str | None = None,
    pdf_path: str | None = None,
) -> AsyncGenerator[str, None]:
    store = get_store()
    source = url or pdf_path

    # Duplicate check
    if url and store.exists(url):
        title = store.get_title_by_url(url)
        if title:
            yield f"Warning: Note already exists: '{title}'. Skipping."
        else:
            yield "Warning: Note for this URL already exists. Skipping."
        return

    # Step 1: Extract
    yield "Extracting content..."
    tmp_pdf_path = None
    images: list[bytes] = []
    try:
        if url:
            doc = await extract(url)
            raw_text = doc.raw_text
            images = doc.images if hasattr(doc, "images") and doc.images else []
        elif pdf_path:
            doc = extract_pdf(pdf_path)
            raw_text = doc.raw_text
            images = doc.images if hasattr(doc, "images") and doc.images else []
        else:
            yield "Error: No url or pdf_path provided."
            return
    except Exception as e:
        yield f"Error during extraction: {e}"
        return
    finally:
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            os.unlink(tmp_pdf_path)

    # Step 1.5: Content quality gate — skip bad extractions (Track A)
    from core.quality_gate import QualityGate
    gate = QualityGate()
    gate_result = gate.check(
        url=url or "",
        raw_text=raw_text,
        keyword="",
        content_type=doc.content_type,
    )
    if not gate_result.pass_:
        yield f"Skipped: {gate_result.reason}"
        return

    # Step 2: Find similar
    yield "Finding similar notes..."
    vector = embed(raw_text[:MAX_EMBED_CHARS])
    similar = store.search(vector, top_k=TOP_K_SIMILAR)
    similar_titles = [
        s["metadata"].get("title", Path(s["path"]).stem)
        for s in similar
        if isinstance(s.get("metadata"), dict)
    ]
    yield f"Finding similar notes ({len(similar)} found)..."

    # Step 3: Enrich
    yield "Enriching with Minimax..."
    if doc.content_type == "video" and len(raw_text) > 60_000:
        # Video + long transcript: use semantic chunking + synthesis
        from core.minimax_client import semantic_chunk, enrich_video_synthesis
        chunks = semantic_chunk(raw_text)
        chunk_results = []
        for chunk in chunks:
            result = await asyncio.to_thread(enrich, chunk.text, similar_titles, source)
            chunk_results.append(result)
        note = await asyncio.to_thread(enrich_video_synthesis, chunk_results, source, similar_titles)
    elif doc.content_type == "video":
        # Video + short transcript: direct enrich (no truncation needed)
        note = await asyncio.to_thread(enrich, raw_text, similar_titles, source)
    else:
        # Article / paper: direct enrich
        note = await asyncio.to_thread(enrich, raw_text, similar_titles, source)

    # Step 3.5a: Check entity status
    yield "Checking entity status..."
    entity_statuses = await asyncio.to_thread(
        fetch_entity_status, note.get("entities") or []
    )

    # Step 3.5b: Gap detection
    note["gap_entities"] = await asyncio.to_thread(detect_gaps, note.get("entities", []))
    if note["gap_entities"]:
        asyncio.create_task(_run_gap_searches(note["gap_entities"]))

    # Step 4: Write
    yield "Saving note..."
    path = write_note(
        note, source=source, images=images, entity_statuses=entity_statuses
    )

    # Step 5: Index
    yield "Indexing..."
    index_meta = {k: v for k, v in note.items() if k != "raw_text"}
    index_meta["_file_path"] = path
    store.upsert(
        path=source,
        text=raw_text,
        vector=vector,
        links=note.get("cross_links", []),
        metadata=index_meta,
    )

    stem = Path(path).name
    yield f"Saved -> notes/{stem}"
