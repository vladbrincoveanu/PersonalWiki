import asyncio
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.embeddings import embed
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

_logger = logging.getLogger(__name__)


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


async def _run_gap_searches(gap_entities: list[dict]):
    from ingesters.router import route_and_ingest
    from core.keywords_manager import KeywordsManager
    from core.keyword_extractor import KeywordExtractor
    from core.vector_store import VectorStore
    from core.bm25_index import BM25Index
    from vault.writer import VaultWriter

    pipeline = Pipeline(
        vector_store=VectorStore(),
        bm25_index=BM25Index(),
        keyword_extractor=KeywordExtractor(),
        keywords_manager=KeywordsManager(),
        vault_writer=VaultWriter(),
    )
    for entity in gap_entities:
        try:
            await route_and_ingest(pipeline, entity.get("search_query", ""), "auto", None)
        except Exception as e:
            _logger.warning("Gap search failed for %s: %s", entity.get("name"), e)


class Pipeline:
    def __init__(
        self,
        vector_store,
        bm25_index,
        keyword_extractor,
        keywords_manager,
        vault_writer,
    ):
        self.vector_store = vector_store
        self.bm25_index = bm25_index
        self.keyword_extractor = keyword_extractor
        self.keywords_manager = keywords_manager
        self.vault_writer = vault_writer

    async def run(
        self,
        url: str | None = None,
        pdf_path: str | None = None,
        docx_path: str | None = None,
        md_path: str | None = None,
        txt_path: str | None = None,
        is_discovery: bool = False,
        source_keyword: str | None = None,
        _state: dict | None = None,
    ) -> dict[str, Any]:
        if not any((url, pdf_path, docx_path, md_path, txt_path)):
            raise ValueError("A content source is required (url or file path).")

        state = _state or {
            "outcome": "success",
            "source_type": _pipeline_source_type(url, pdf_path, docx_path, md_path, txt_path),
        }
        store = get_store()
        source = url or pdf_path or docx_path or md_path or txt_path

        # Step 1: Extract
        with _pipeline_stage("extract", state["source_type"]):
            if url:
                doc = await extract(url)
            elif pdf_path:
                doc = await extract_pdf(pdf_path)
            elif docx_path:
                doc = await extract_docx(docx_path)
            elif md_path:
                doc = await extract_markdown(md_path)
            elif txt_path:
                from ingesters.router import extract_text
                doc = await extract_text(txt_path)
            else:
                raise ValueError("No valid source provided")

        raw_text = doc.text
        images = doc.images
        content_type = doc.content_type

        # Step 2: Enrich
        with _pipeline_stage("enrich", state["source_type"]):
            note = await self._enrich_note(raw_text, content_type, source)

        # Step 3: Entity extraction
        with _pipeline_stage("entity_extraction", state["source_type"]):
            note["entities"] = _merge_entities(note.get("entities"))

        # Step 3.5a: Check entity status
        with _pipeline_stage("entity_status", state["source_type"]):
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
        with _pipeline_stage("write", state["source_type"]):
            path = write_note(
                note, source=source, images=images, entity_statuses=entity_statuses,
                is_discovery=is_discovery, source_keyword=source_keyword,
            )

        # Step 5: Index
        with _pipeline_stage("index", state["source_type"]):
            vector = embed(note["content"])
            store.upsert(path, note["content"], vector, note.get("metadata", {}))

        record_pipeline_run(state["source_type"], state["outcome"])
        return {"path": path, "note": note}

    async def _enrich_note(self, text: str, content_type: str, source: str) -> dict:
        # This is a placeholder - the actual enrichment happens in the ingesters
        return {
            "content": text,
            "content_type": content_type,
            "source": source,
            "metadata": {},
        }


def get_store():
    from core.vector_store import get_vector_store
    return get_vector_store()
