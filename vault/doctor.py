# vault/doctor.py
"""
Vault doctor — diagnose and clean up junk notes.

Detects and removes:
- Video notes with no transcript content
- Untitled notes (no H1, exact "untitled", or H1 starts with "untitled")
- Notes with [NO_TRANSCRIPT] or [TRANSLATION_FAILED] in title
- Notes with empty body
- Sparse notes with < 200 chars raw_text
- Orphaned discovery notes: discovery: auto with a source keyword no longer
  active, and no wikilink to the source keyword or an active keyword
"""
import logging
import re
import frontmatter
from config import NOTES_DIR

_logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Lowercase, replace non-alphanumeric with dash, strip hyphens."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug


def _is_junk_note(
    note: dict, active_keywords: list[str], file_stem: str | None = None
) -> tuple[bool, str]:
    """
    Return (is_junk, reason) where reason is one of:
    video-no-content, untitled-no-h1, untitled-exact, untitled-h1,
    transcript-failed, no-body, sparse, orphaned-discovery-no-keyword-link,
    or "" if not junk.

    ``file_stem`` is retained as an optional compatibility argument for older
    callers; the detector does not need the path to make its decision.
    """
    title = note.get("title", "")
    body = note.get("body", note.get("raw_text", ""))
    raw_text = note.get("raw_text", "")
    note_type = note.get("type", "")

    is_video = note_type == "video"

    # Transcript failed marker in title
    if "[NO_TRANSCRIPT]" in title or "[TRANSLATION_FAILED]" in title:
        return True, "transcript-failed"

    # Untitled exact
    if title.lower() == "untitled":
        return True, "untitled-exact"

    # Video with no/short transcript
    if is_video and len(raw_text) < 50:
        return True, "video-no-content"

    # Non-video checks
    if not is_video:
        if not body.strip():
            return True, "no-body"
        if not re.search(r"^#\s", body, re.MULTILINE):
            return True, "untitled-no-h1"
        first_line = body.split("\n", 1)[0]
        if re.match(r"^#\s*untitled$", first_line, re.IGNORECASE):
            return True, "untitled-h1"

    # Orphaned discovery — only auto-discovered notes with a declared source
    # keyword are eligible. Normal/manual notes commonly have no source
    # keyword and must never be deleted by the legacy cleanup wrapper.
    discovery = note.get("discovery", "")
    source_keyword = note.get("source_keyword", "")
    if discovery == "auto" and source_keyword and source_keyword not in active_keywords:
        has_own_link = (
            f"[[{source_keyword}]]" in body
            or f"[[{_slugify(source_keyword)}]]" in body
        ) if source_keyword else False
        has_keyword_link = any(
            f"[[{kw}]]" in body or f"[[{_slugify(kw)}]]" in body
            for kw in active_keywords
        )
        if not has_own_link and not has_keyword_link:
            return True, "orphaned-discovery-no-keyword-link"

    # Sparse — raw_text < 200 chars
    if len(raw_text) < 200:
        return True, "sparse"

    return False, ""


def run_vault_doctor(active_keywords: list[str]) -> dict[str, list[str]]:
    """
    Scan NOTES_DIR for junk notes and delete them from vault + vector store.

    Returns dict with keys: "untitled", "sparse", "orphaned", "video-no-content", "deleted"
    """
    from core.vector_store import get_store

    if not NOTES_DIR.exists():
        return {"untitled": [], "sparse": [], "orphaned": [], "video-no-content": [], "deleted": []}

    store = get_store()
    results: dict[str, list[str]] = {
        "untitled": [],
        "sparse": [],
        "orphaned": [],
        "video-no-content": [],
        "deleted": [],
    }

    for md_path in NOTES_DIR.rglob("*.md"):
        try:
            metadata, content = frontmatter.parse(md_path.read_text(encoding="utf-8"))
            note = dict(metadata)
            note["raw_text"] = content
            note["body"] = content

            is_junk, reason = _is_junk_note(note, active_keywords)
            if not is_junk:
                continue

            _logger.info("Vault doctor: removing %s (%s)", md_path.name, reason)
            md_path.unlink()
            # Remove from vector store
            try:
                store.delete(str(md_path))
            except Exception as e:
                _logger.warning("Vault doctor: failed to delete from vector store: %s", e)
            results["deleted"].append(str(md_path))

            if reason in ("untitled-no-h1", "untitled-exact", "untitled-h1"):
                results["untitled"].append(str(md_path))
            elif reason == "sparse":
                results["sparse"].append(str(md_path))
            elif reason in ("orphaned-discovery", "orphaned-discovery-no-keyword-link"):
                results["orphaned"].append(str(md_path))
            elif reason == "video-no-content":
                results["video-no-content"].append(str(md_path))

        except Exception as e:
            _logger.warning("Vault doctor: failed to process %s: %s", md_path.name, e)

    return results


def cleanup_junk() -> list[str]:
    """
    Legacy wrapper for backward compatibility.
    Calls run_vault_doctor([]) and returns only the "deleted" list.
    """
    return run_vault_doctor([])["deleted"]
