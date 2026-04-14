"""Keywords manager for manual keyword persistence."""

from pathlib import Path


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

    Raises ValueError if keyword already exists.
    """
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
