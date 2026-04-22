"""Keywords manager for manual keyword persistence."""

from pathlib import Path


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


def remove_keyword(keyword: str, path: Path, vault_path: Path | None = None) -> list[str]:
    """Remove keyword from _keywords file and cascade delete source_keyword matches.

    Args:
        keyword: keyword to remove
        path: path to _keywords file
        vault_path: path to vault for cascade delete (optional for backwards compat)

    Returns list of deleted file paths from cascade.
    Raises KeyError if keyword not found.
    """
    existing = load_manual_keywords(path)
    if keyword not in existing:
        raise KeyError(f"Keyword '{keyword}' not found in {path}")
    existing.remove(keyword)
    save_manual_keywords(existing, path)

    cascade_deleted = []
    if vault_path and vault_path.exists():
        cascade_deleted = _cascade_delete_by_source_keyword(keyword, vault_path)

    return cascade_deleted


def _cascade_delete_by_source_keyword(keyword: str, vault_path: Path) -> list[str]:
    """Delete all notes where source_keyword frontmatter equals keyword.

    Returns list of deleted file paths.
    """
    import frontmatter as fm
    from core.vector_store import get_store

    deleted = []
    try:
        store = get_store()
    except Exception:
        store = None

    for md_file in vault_path.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            parsed = fm.parse(content)
            if parsed is None:
                continue
            metadata, _ = parsed
            if metadata.get("source_keyword") == keyword:
                md_file.unlink()
                if store:
                    try:
                        store.delete(str(md_file))
                    except Exception:
                        pass
                deleted.append(str(md_file))
        except Exception:
            continue

    return deleted


def purge_keyword(keyword: str, vault_path: Path) -> list[str]:
    """Remove [[wikilink]] references to keyword from vault .md files.

    Orphan stubs (files that are essentially just the keyword as a title with
    no meaningful body content) are deleted. Files with real content are kept
    but have their [[keyword]] wikilinks stripped.

    Returns list of deleted file paths.
    """
    import re

    wikilink_pattern = re.compile(rf"\[\[{re.escape(keyword)}\]\]", re.IGNORECASE)
    deleted = []

    for md_file in vault_path.rglob("*.md"):
        try:
            raw = md_file.read_text(encoding="utf-8")
            has_wikilink = bool(wikilink_pattern.search(raw))

            # Detect orphan stub: file whose filename (stem) exactly matches the keyword
            # This catches stubs created when pipeline saves a file with no body content
            is_title_orphan = md_file.stem.lower() == keyword.lower()

            if not has_wikilink and not is_title_orphan:
                continue

            # Separate frontmatter from body
            fm = ""
            body = raw
            if body.startswith("---"):
                fm_end = body.find("\n---", 3)
                if fm_end != -1:
                    fm = body[: fm_end + 4]
                    body = body[fm_end + 4 :]

            # Strip H1 title line if it's just # keyword
            first_line = body.split("\n", 1)[0] if body else ""
            if first_line.strip().lower() == f"# {keyword}".lower():
                body = body[len(first_line) :]

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
            else:
                if fm:
                    md_file.write_text(fm + "\n" + new_body + "\n", encoding="utf-8")
                else:
                    md_file.write_text(new_body + "\n", encoding="utf-8")
        except Exception:
            continue

    return deleted
