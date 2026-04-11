import asyncio
import os
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from typing import AsyncGenerator
from config import TOP_K_SIMILAR, MAX_EMBED_CHARS
from core.embeddings import embed
from core.vector_store import get_store
from core.minimax_client import enrich
from ingesters.web import extract_url
from ingesters.pdf import extract_pdf, extract_pdf_full
from vault.writer import write_note


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
    tmp_pdf_path = None
    images: list[bytes] = []
    try:
        if url and _is_pdf_url(url):
            yield "Detected PDF URL — downloading..."
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_pdf_path = tmp.name
            await asyncio.to_thread(urllib.request.urlretrieve, url, tmp_pdf_path)
            result = await asyncio.to_thread(extract_pdf_full, tmp_pdf_path)
            raw_text = result.markdown
            images = result.images
        elif url:
            raw_text = await extract_url(url)
        else:
            result = await asyncio.to_thread(extract_pdf_full, pdf_path)
            raw_text = result.markdown
            images = result.images
    except Exception as e:
        yield f"Error during extraction: {e}"
        return
    finally:
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            os.unlink(tmp_pdf_path)

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
    path = write_note(note, source=source, images=images)

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
