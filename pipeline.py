import asyncio
from pathlib import Path
from typing import AsyncGenerator
from config import TOP_K_SIMILAR, MAX_EMBED_CHARS
from core.embeddings import embed
from core.vector_store import get_store
from core.minimax_client import enrich
from ingesters.web import extract_url
from ingesters.pdf import extract_pdf
from vault.writer import write_note


async def run_pipeline(
    url: str | None = None,
    pdf_path: str | None = None,
) -> AsyncGenerator[str, None]:
    store = get_store()
    source = url or pdf_path

    # Duplicate check
    if url and store.exists(url):
        yield "Warning: Note for this URL already exists. Skipping."
        return

    # Step 1: Extract
    yield "Extracting content..."
    try:
        if url:
            raw_text = await extract_url(url)
        else:
            raw_text = await asyncio.to_thread(extract_pdf, pdf_path)
    except Exception as e:
        yield f"Error during extraction: {e}"
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
    note = await asyncio.to_thread(enrich, raw_text, similar_titles, source)

    # Step 4: Write
    yield "Saving note..."
    path = write_note(note, source=source)

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
