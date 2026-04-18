import asyncio
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import AsyncGenerator
from config import TOP_K_SIMILAR, MAX_EMBED_CHARS
from core.embeddings import embed
from core.prose import measure_prose
from core.vector_store import get_store
from core.minimax_client import enrich, _MIN_CHUNK_SIZE
from core.gap_detector import detect_gaps
from ingesters.router import extract, extract_pdf, extract_docx, extract_markdown
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


def _gate_enriched_content(note: dict, raw_text: str) -> tuple[bool, int, float]:
    """Return (pass, prose_chars, prose_ratio) for enriched content quality check.

    Checks:
    - Hard minimum: total prose chars >= 300
    - Prose ratio: prose_chars / raw_text_chars >= 0.20
    - Video-specific: raw_text must have >= 5 words with at least one alpha char
    """
    summary = note.get("summary", "") or ""
    key_facts_list = note.get("key_facts", [])
    key_facts = " ".join(key_facts_list) if key_facts_list else ""
    enriched_text = (summary + " " + key_facts).strip()

    prose_chars, _ = measure_prose(enriched_text)
    total_chars = len(raw_text.strip())
    prose_ratio = prose_chars / total_chars if total_chars > 0 else 0.0

    # Hard minimum: need meaningful prose
    if prose_chars < 300:
        return False, prose_chars, prose_ratio

    # Prose ratio: content must not be mostly noise
    # DISABLED: was rejecting valid YouTube transcripts with high timestamp density
    # if total_chars > 0 and prose_ratio < 0.20:
    #     return False, prose_chars, prose_ratio

    # Video-specific: raw_text must have actual words (not just timestamps)
    if note.get("type") == "video":
        words = [w for w in raw_text.split() if any(c.isalpha() for c in w)]
        if len(words) < 5:
            return False, prose_chars, prose_ratio

    return True, prose_chars, prose_ratio


async def run_pipeline(
    url: str | None = None,
    pdf_path: str | None = None,
    docx_path: str | None = None,
    md_path: str | None = None,
    txt_path: str | None = None,
    is_discovery: bool = False,
) -> AsyncGenerator[str, None]:
    import logging
    _logger = logging.getLogger(__name__)
    store = get_store()
    source = url or pdf_path or docx_path or md_path or txt_path

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
    images: list[bytes] = []
    try:
        if url:
            doc = await extract(url)
            raw_text = doc.raw_text
            images = getattr(doc, 'images', None) or []
        elif pdf_path:
            yield "Extracting PDF..."
            doc = await asyncio.to_thread(extract_pdf, pdf_path)
            raw_text = doc.raw_text
            images = getattr(doc, 'images', None) or []
        elif docx_path:
            doc = await asyncio.to_thread(extract_docx, docx_path)
            raw_text = doc.raw_text
            images = []
        elif md_path:
            doc = await asyncio.to_thread(extract_markdown, md_path)
            raw_text = doc.raw_text
            images = []
        elif txt_path:
            doc = await asyncio.to_thread(extract_markdown, txt_path)  # Reuse markdown extractor (plain text)
            raw_text = doc.raw_text
            images = []
        else:
            yield "Error: No url or file provided."
            return
    except Exception as e:
        yield f"Error during extraction: {e}"
        return

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
    if doc.content_type == "video" and len(raw_text) > _MIN_CHUNK_SIZE:
        # Video + long transcript: use semantic chunking + synthesis
        from core.minimax_client import semantic_chunk, enrich_video_synthesis
        chunks = await asyncio.to_thread(semantic_chunk, raw_text)
        chunk_results = await asyncio.gather(*[
            asyncio.to_thread(enrich, chunk.text, similar_titles, source)
            for chunk in chunks
        ])
        note = await asyncio.to_thread(enrich_video_synthesis, list(chunk_results), source, similar_titles)
    elif doc.content_type == "video":
        # Video + short transcript: direct enrich (no truncation needed)
        note = await asyncio.to_thread(enrich, raw_text, similar_titles, source)
    else:
        # Article / paper: direct enrich
        note = await asyncio.to_thread(enrich, raw_text, similar_titles, source)

    # Step 3.1: Pre-write content quality gate — reject thin/noise-heavy enriched content
    gate_pass, prose_chars, prose_ratio = _gate_enriched_content(note, raw_text)
    if not gate_pass:
        yield f"Skipped: Content too thin (prose={prose_chars}, ratio={prose_ratio:.0%}, need ≥300 chars, ≥20%)"
        return

    # Step 3.5a: Check entity status
    yield "Checking entity status..."
    entity_statuses = await asyncio.to_thread(
        fetch_entity_status, note.get("entities") or []
    )

    # Step 3.5b: Gap detection
    note["gap_entities"] = await asyncio.to_thread(detect_gaps, note.get("entities", []))
    if note["gap_entities"]:
        gap_task = asyncio.create_task(_run_gap_searches(note["gap_entities"]))
        gap_task.add_done_callback(
            lambda t: _logger.debug("Gap search completed: %s", t.result())
            if not t.cancelled() and t.exception() is None
            else _logger.warning("Gap search failed: %s", t.exception())
        )

    # Step 4: Write
    yield "Saving note..."
    path = write_note(
        note, source=source, images=images, entity_statuses=entity_statuses,
        is_discovery=is_discovery,
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
