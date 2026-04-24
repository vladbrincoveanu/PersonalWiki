# vault/doctor.py
"""
Vault doctor — diagnose and clean up junk notes.

Detects and removes:
- Video notes with no transcript content
- Untitled notes (no H1, exact "untitled", or H1 starts with "untitled")
- Notes with [NO_TRANSCRIPT] or [TRANSLATION_FAILED] in title
- Notes with empty body
- Sparse notes with < 200 chars raw_text
- Orphaned notes: source_keyword not in active keywords (or blank),
  AND body has no wikilink to its own source_keyword,
  AND body has no wikilink to any active keyword
"""
import logging
import re
from pathlib import Path
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


def _is_junk_note(note: dict, active_keywords: list[str], file_stem: str) -> tuple[bool, str]:
    """
    Return (is_junk, reason) where reason is one of:
    video-no-content, untitled-no-h1, untitled-exact, untitled-h1,
    transcript-failed, no-body, sparse, orphaned-discovery,
    orphaned-discovery-no-keyword-link, or "" if not junk.
    """
    title = note.get("title", "")
    body = note.get("body", note.get("raw_text", ""))
    raw_text = note.get("raw_text", "")
    note_type = note.get("type", "")

    # Transcript failed marker in title
    if "[NO_TRANSCRIPT]" in title or "[TRANSLATION_FAILED]" in title:
        return True, "transcript-failed"

    # Untitled exact
    if title.lower() == "untitled":
        return True, "untitled-exact"

    # Video with no/short transcript — check BEFORE untitled/no-body for videos
    if note_type == "video" and len(raw_text) < 50:
        return True, "video-no-content"

    # No body — skip for videos (body == raw_text for videos, handled by video-no-content)
    if note_type != "video" and not body.strip():
        return True, "no-body"

    # Untitled no H1 — no "# " heading in body (skip for videos)
    if note_type != "video" and not re.search(r"^#\s", body, re.MULTILINE):
        return True, "untitled-no-h1"

    # H1 untitled — first line starts "# untitled" (case-insensitive, skip for videos)
    if note_type != "video":
        first_line = body.split("\n", 1)[0]
        if re.match(r"^#\s*untitled$", first_line, re.IGNORECASE):
            return True, "untitled-h1"

    # Orphaned — source_keyword not in active_keywords (or blank)
    # AND body has no wikilink to its own declared source_keyword
    # AND body has no wikilink to any active keyword
    source_keyword = note.get("source_keyword", "")
    if source_keyword not in active_keywords:
        # Check if body links to its own source_keyword
        own_link = f"[[{source_keyword}]]" if source_keyword else ""
        own_link_slug = f"[[{_slugify(source_keyword)}]]" if source_keyword else ""
        has_own_link = (own_link in body or own_link_slug in body) if source_keyword else False

        # Check if body links to any active keyword
        has_keyword_link = False
        for kw in active_keywords:
            if f"[[{kw}]]" in body or f"[[{_slugify(kw)}]]" in body:
                has_keyword_link = True
                break

        if not has_own_link and not has_keyword_link:
            return True, "orphaned-no-keyword-link"
        # Has wikilink to own source or any active keyword — not junk

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

            is_junk, reason = _is_junk_note(note, active_keywords, md_path.stem)
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
            elif reason in ("orphaned-discovery", "orphaned-no-keyword-link"):
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
