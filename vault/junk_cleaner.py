# vault/junk_cleaner.py
"""
Vault junk cleaner — removes video notes with no transcript content.
"""
import logging
from pathlib import Path
import frontmatter
from config import NOTES_DIR

_logger = logging.getLogger(__name__)

def _is_junk_note(note: dict) -> bool:
    """Return True if a note should be deleted as junk."""
    title = note.get("title", "")
    if "[NO_TRANSCRIPT]" in title or "[TRANSLATION_FAILED]" in title:
        return True
    if note.get("type") != "video":
        return False
    raw_text = note.get("raw_text", "")
    return len(raw_text) < 50

def cleanup_junk() -> list[str]:
    """
    Scan NOTES_DIR for junk video notes and delete them from vault + vector store.
    Returns list of deleted file paths.
    """
    if not NOTES_DIR.exists():
        return []

    from core.vector_store import get_store
    store = get_store()
    deleted: list[str] = []

    for md_path in NOTES_DIR.glob("*.md"):
        try:
            post = frontmatter.parse(md_path.read_text(encoding="utf-8"))
            note = dict(post)
            note["raw_text"] = post.content
            if not _is_junk_note(note):
                continue
            _logger.info("Junk cleanup: removing %s", md_path.name)
            md_path.unlink()
            # Remove from vector store
            store.delete(str(md_path))
            deleted.append(str(md_path))
        except Exception as e:
            _logger.warning("Junk cleanup: failed to process %s: %s", md_path.name, e)

    return deleted