import asyncio
import time
from contextlib import contextmanager
from pathlib import Path
from typing import AsyncGenerator
from config import TOP_K_SIMILAR, MAX_EMBED_CHARS
from core.embeddings import embed
from core.prose import measure_prose
from core.vector_store import get_store
from core.minimax_client import enrich, enrich_with_images, _MIN_CHUNK_SIZE
from core.gap_detector import detect_gaps
from core.observability import (
    configure_observability,
    observed_span,
    record_handled_error,
    record_pipeline_run,
    record_pipeline_stage,
    stable_source_hash,
)
from ingesters.router import extract, extract_pdf, extract_docx, extract_markdown
from vault.writer import write_note
from vault.entity_status import fetch_entity_status


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


def _merge_entities(*entity_groups: list[dict] | None) -> list[dict]:
    """Merge entity sources while retaining image-derived entities first."""
    merged: list[dict] = []
    seen: set[str] = set()
    for group in entity_groups:
        if not isinstance(group, list):
            continue
        for entity in group:
            if not isinstance(entity, dict):
                continue
            identity = entity.get("slug") or entity.get("name") or entity.get("entity_name")
            key = str(identity).strip().casefold() if identity else ""
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(entity)
    return merged


def _pipeline_source_type(
    url: str | None,
    pdf_path: str | None,
    docx_path: str | None,
    md_path: str | None,
    txt_path: str | None,
) -> str:
    if url:
        return "url"
    if pdf_path:
        return "pdf"
    if docx_path:
        return "docx"
    if md_path:
        return "md"
    if txt_path:
        return "txt"
    return "other"


@contextmanager
def _pipeline_stage(stage: str, source_type: str):
    started = time.perf_counter()
    result = {"outcome": "success"}
    try:
        with observed_span(
            f"personalwiki.pipeline.{stage}",
            {"stage": stage},
        ) as span:
            try:
                yield span, result
            except Exception:
                result["outcome"] = "error"
                raise
    finally:
        record_pipeline_stage(
            stage,
            source_type,
            result["outcome"],
            time.perf_counter() - started,
        )


async def run_pipeline(
    url: str | None = None,
    pdf_path: str | None = None,
    docx_path: str | None = None,
    md_path: str | None = None,
    txt_path: str | None = None,
    is_discovery: bool = False,
    source_keyword: str | None = None,
    keywords: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    configure_observability()
    source = url or pdf_path or docx_path or md_path or txt_path
    state = {
        "outcome": "success",
        "source_type": _pipeline_source_type(url, pdf_path, docx_path, md_path, txt_path),
    }
    started = time.perf_counter()
    with observed_span(
        "personalwiki.pipeline.run",
        {
            "pipeline.source_type": state["source_type"],
            "pipeline.trigger": "discovery" if is_discovery else "manual",
            "source_hash": stable_source_hash(source) if source else None,
        },
    ) as root_span:
        try:
            async for message in _run_pipeline_impl(
                url=url,
                pdf_path=pdf_path,
                docx_path=docx_path,
                md_path=md_path,
                txt_path=txt_path,
                is_discovery=is_discovery,
                source_keyword=source_keyword,
                keywords=keywords,
                _state=state,
            ):
                yield message
        except Exception:
            state["outcome"] = "error"
            raise
        finally:
            if root_span is not None:
                root_span.set_attribute("pipeline.source_type", state["source_type"])
                root_span.set_attribute("pipeline.outcome", state["outcome"])
            record_pipeline_run(
                state["source_type"],
                "discovery" if is_discovery else "manual",
                state["outcome"],
                time.perf_counter() - started,
            )


async def _run_pipeline_impl(
    url: str | None = None,
    pdf_path: str | None = None,
    docx_path: str | None = None,
    md_path: str | None = None,
    txt_path: str | None = None,
    is_discovery: bool = False,
    source_keyword: str | None = None,
    keywords: list[str] | None = None,
    _state: dict[str, str] | None = None,
) -> AsyncGenerator[str, None]:
    import logging
    _logger = logging.getLogger(__name__)
    state = _state or {
        "outcome": "success",
        "source_type": _pipeline_source_type(url, pdf_path, docx_path, md_path, txt_path),
    }
    if not any((url, pdf_path, docx_path, md_path, txt_path)):
        raise ValueError("A content source is required (url or file path).")
    store = get_store()
    source = url or pdf_path or docx_path or md_path or txt_path

    # Duplicate check
    if url and store.exists(url):
        title = store.get_title_by_url(url)
        if title:
            yield f"Warning: Note already exists: '{title}'. Skipping."
        else:
            yield "Warning: Note for this URL already exists. Skipping."
        state["outcome"] = "skipped"
        return

    # Step 1: Extract
    yield "Extracting content..."
    images: list[bytes] = []
    extraction_error: Exception | None = None
    no_source = False
    with _pipeline_stage("extract", state["source_type"]) as (extract_span, extract_result):
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
                no_source = True
                extract_result["outcome"] = "skipped"
        except Exception as e:
            record_handled_error(extract_span, e)
            extract_result["outcome"] = "error"
            extraction_error = e

    if no_source:
        yield "Error: No url or file provided."
        state["outcome"] = "skipped"
        return
    if extraction_error is not None:
        yield f"Error during extraction: {extraction_error}"
        state["outcome"] = "error"
        return

    content_type = doc.content_type if doc.content_type in {"article", "paper", "video"} else "other"
    state["source_type"] = content_type

    # Step 1.5: Content quality gate — skip bad extractions (Track A)
    from core.quality_gate import QualityGate
    gate = QualityGate()
    with _pipeline_stage("quality_gate", state["source_type"]) as (_, quality_result):
        gate_result = gate.check(
            url=url or "",
            raw_text=raw_text,
            keyword="",
            content_type=doc.content_type,
        )
        if not gate_result.pass_:
            quality_result["outcome"] = "skipped"
    if not gate_result.pass_:
        yield f"Skipped: {gate_result.reason}"
        state["outcome"] = "skipped"
        return

    # Step 2: Find similar
    yield "Finding similar notes..."
    with _pipeline_stage("embed", state["source_type"]):
        vector = embed(raw_text[:MAX_EMBED_CHARS])
    with _pipeline_stage("vector_search", state["source_type"]):
        similar = store.search(vector, top_k=TOP_K_SIMILAR)
        similar_titles = [
            s["metadata"].get("title", Path(s["path"]).stem)
            for s in similar
            if isinstance(s.get("metadata"), dict)
        ]
    yield f"Finding similar notes ({len(similar)} found)..."

    # Step 3: Enrich
    yield "Enriching with Minimax..."
    with _pipeline_stage("enrich", state["source_type"]):
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
            if images:
                note = await asyncio.to_thread(enrich_with_images, raw_text, similar_titles, source, images)
            else:
                note = await asyncio.to_thread(enrich, raw_text, similar_titles, source)

    # Step 3.1: Pre-write content quality gate — reject thin/noise-heavy enriched content
    with _pipeline_stage("quality_gate", state["source_type"]) as (_, enriched_quality_result):
        gate_pass, prose_chars, prose_ratio = _gate_enriched_content(note, raw_text)
        if not gate_pass:
            enriched_quality_result["outcome"] = "skipped"
    if not gate_pass:
        yield f"Skipped: Content too thin (prose={prose_chars}, ratio={prose_ratio:.0%}, need ≥300 chars, ≥20%)"
        state["outcome"] = "skipped"
        return

    # Enrichment already extracts entities; normalize them without making a
    # second LLM call through a separate provider-specific extractor.
    with _pipeline_stage("entity_status", state["source_type"]):
        note["entities"] = _merge_entities(note.get("entities"))

        # Step 3.5a: Check entity status
        yield "Checking entity status..."
        entity_statuses = await asyncio.to_thread(
            fetch_entity_status, note.get("entities") or []
        )

    # Step 3.5b: Gap detection
    with _pipeline_stage("gap_detection", state["source_type"]):
        note["gap_entities"] = await asyncio.to_thread(detect_gaps, note.get("entities", []))
        if note["gap_entities"]:
            gap_task = asyncio.create_task(_run_gap_searches(note["gap_entities"]))
            gap_task.add_done_callback(
                lambda t: _logger.debug("Gap search completed: %s", t.result())
                if not t.cancelled() and t.exception() is None
                else _logger.warning("Gap search failed: %s", t.exception())
            )

    # Step 4: Write
    with _pipeline_stage("vault_write", state["source_type"]):
        yield "Saving note..."
        path = write_note(
            note, source=source, images=images, entity_statuses=entity_statuses,
            is_discovery=is_discovery, source_keyword=source_keyword,
            keywords=keywords,
        )

    # Step 5: Index
    with _pipeline_stage("vector_upsert", state["source_type"]):
        yield "Indexing..."
        index_meta = {k: v for k, v in note.items() if k != "raw_text"}
        index_meta["_file_path"] = path
        index_meta["_indexed_at"] = time.time()
        store.upsert(
            path=source,
            text=raw_text,
            vector=vector,
            links=note.get("cross_links", []),
            metadata=index_meta,
        )

    for entity in note.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        entity_name = entity.get("entity_name") or entity.get("name")
        if not entity_name:
            continue
        store.upsert_entity(
            path=path,
            entity_type=entity.get("entity_type") or entity.get("type") or "other",
            entity_name=str(entity_name),
            summary=str(entity.get("summary") or ""),
            metadata=entity.get("metadata") if isinstance(entity.get("metadata"), dict) else {},
        )

    stem = Path(path).name
    yield f"Saved -> notes/{stem}"
