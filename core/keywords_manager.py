"""Keywords manager for manual keyword persistence."""

import logging
import re
from pathlib import Path

try:
    import frontmatter as fm
except ImportError:
    fm = None  # type: ignore

_logger = logging.getLogger(__name__)


def _suppressed_path(path: Path) -> Path:
    """Return the suppressed blocklist path for a given keywords file."""
    return path.parent / (path.name + "-suppressed")


def load_manual_keywords(path: Path) -> list[str]:
    """Read keywords from a _keywords file.

    One keyword per line. Blank lines and # comments are ignored.
    Returns empty list if file does not exist.
    """
    if not path.exists():
        return []
    keywords = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        keywords.append(line)
    return keywords


def load_suppressed_keywords(path: Path) -> list[str]:
    """Read suppressed graph keywords from the blocklist file.

    Returns empty list if no blocklist exists.
    """
    suppressed_file = _suppressed_path(path)
    if not suppressed_file.exists():
        return []
    keywords = []
    for line in suppressed_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        keywords.append(line)
    return keywords


def save_manual_keywords(keywords: list[str], path: Path) -> None:
    """Write keywords to a _keywords file.

    One keyword per line.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(keywords) + "\n", encoding="utf-8")


def add_keyword(keyword: str, path: Path) -> None:
    """Append keyword to _keywords file.

    Raises ValueError if keyword already exists or is a URL.
    """
    if keyword.startswith("http://") or keyword.startswith("https://"):
        raise ValueError(f"Keyword cannot be a URL: {keyword!r}. Use a topic word or phrase instead.")
    existing = load_manual_keywords(path)
    if keyword in existing:
        raise ValueError(f"Keyword '{keyword}' already exists in {path}")
    existing.append(keyword)
    save_manual_keywords(existing, path)


def remove_keyword(keyword: str, path: Path) -> None:
    """Remove keyword from _keywords file.

    Raises KeyError if keyword is not found.
    """
    existing = load_manual_keywords(path)
    if keyword not in existing:
        raise KeyError(f"Keyword '{keyword}' not found in {path}")
    existing.remove(keyword)
    save_manual_keywords(existing, path)


def suppress_keyword(keyword: str, path: Path) -> None:
    """Add a graph keyword to the suppressed blocklist so it won't be rediscovered."""
    suppressed = load_suppressed_keywords(path)
    if keyword in suppressed:
        return
    suppressed.append(keyword)
    suppressed_file = _suppressed_path(path)
    suppressed_file.parent.mkdir(parents=True, exist_ok=True)
    suppressed_file.write_text("\n".join(suppressed) + "\n", encoding="utf-8")


def _cascade_delete_by_source_keyword(keyword: str, vault_path: Path) -> list[str]:
    """Delete all notes where source_keyword frontmatter equals keyword.

    Returns list of deleted file paths.
    """
    from core.vector_store import get_store

    deleted: list[str] = []
    store = None
    try:
        store = get_store()
    except Exception as e:
        _logger.debug("Could not get vector store for cascade delete: %s", e)

    for md_file in vault_path.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            if fm is None:
                _logger.debug("frontmatter module not available, skipping %s", md_file)
                continue
            parsed = fm.parse(content)
            metadata, _ = parsed
            if metadata.get("source_keyword") == keyword:
                md_file.unlink()
                deleted.append(str(md_file))
                if store:
                    try:
                        store.delete(str(md_file))
                    except Exception as e:
                        _logger.debug("Failed to delete %s from vector store: %s", md_file, e)
        except Exception as e:
            _logger.debug("Error processing %s during cascade delete: %s", md_file, e)
            continue

    return deleted


def purge_keyword(keyword: str, vault_path: Path) -> list[str]:
    """Remove [[wikilink]] references to keyword from vault .md files.

    Orphan stubs (files that are essentially just the keyword as a title with
    no meaningful body content) are deleted. Files with real content are kept
    but have their [[keyword]] wikilinks stripped.

    Returns list of deleted file paths.
    """
    from core.vector_store import get_store

    wikilink_pattern = re.compile(rf"\[\[{re.escape(keyword)}\]\]", re.IGNORECASE)
    deleted: list[str] = []
    store = None
    try:
        store = get_store()
    except Exception as e:
        _logger.debug("Could not get vector store for purge: %s", e)

    for md_file in vault_path.rglob("*.md"):
        try:
            raw = md_file.read_text(encoding="utf-8")
            has_wikilink = bool(wikilink_pattern.search(raw))

            # Detect orphan stub: file whose filename (stem) exactly matches the keyword
            is_title_orphan = md_file.stem.lower() == keyword.lower()

            if not has_wikilink and not is_title_orphan:
                continue

            # Use frontmatter library for consistent parsing
            if fm is None:
                _logger.debug("frontmatter module not available, skipping %s", md_file)
                continue

            parsed = fm.parse(raw)
            metadata, body = parsed

            # Strip H1 title line if it's just # keyword
            first_line = body.split("\n", 1)[0] if body else ""
            if first_line.strip().lower() == f"# {keyword}".lower():
                body = body[len(first_line):]

            if has_wikilink:
                # Replace [[keyword]] with keyword, then remove entirely-empty lines
                lines = []
                for line in body.splitlines():
                    cleaned = wikilink_pattern.sub(keyword, line)
                    if not cleaned.strip():
                        continue
                    lines.append(cleaned)
                new_body = "\n".join(lines).strip()
            else:
                new_body = body.strip()

            # Delete orphan stub: if remaining content is just the keyword word
            stripped = new_body.strip().lower()
            is_orphan = (
                not stripped
                or stripped == keyword.lower()
                or stripped == f"{keyword.lower()}."
            )

            if is_orphan:
                md_file.unlink()
                deleted.append(str(md_file))
                if store:
                    try:
                        store.delete(str(md_file))
                    except Exception as e:
                        _logger.debug("Failed to delete %s from vector store: %s", md_file, e)
            else:
                # Reconstruct with frontmatter preserved
                if metadata:
                    import io
                    dump_buffer = io.StringIO()
                    fm.dump(metadata, dump_buffer)
                    fm_text = dump_buffer.getvalue()
                    new_content = fm_text + new_body + "\n"
                else:
                    new_content = new_body + "\n"
                md_file.write_text(new_content, encoding="utf-8")
        except Exception as e:
            _logger.debug("Error processing %s during purge: %s", md_file, e)
            continue

    return deleted
