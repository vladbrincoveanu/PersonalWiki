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
    """Delete all .md files in vault_path containing keyword (as [[wikilink]] or raw text).

    Returns list of deleted file paths.
    """
    deleted = []
    for md_file in vault_path.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            if keyword in content or f"[[{keyword}]]" in content:
                md_file.unlink()
                deleted.append(str(md_file))
        except Exception:
            continue
    return deleted
