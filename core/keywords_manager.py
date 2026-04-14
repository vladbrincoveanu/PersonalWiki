"""Keywords manager for manual keyword persistence."""

from pathlib import Path


def load_manual_keywords(path: Path) -> list[str]:
    """Read keywords from a .interests file.

    One keyword per line. Blank lines and # comments are ignored.
    Returns empty list if file does not exist.
    """
    if not path.exists():
        return []
    keywords = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        keywords.append(line)
    return keywords


def save_manual_keywords(keywords: list[str], path: Path) -> None:
    """Write keywords to a .interests file.

    One keyword per line.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(keywords) + "\n")


def add_keyword(keyword: str, path: Path) -> None:
    """Append keyword to .interests file.

    Raises ValueError if keyword already exists.
    Creates parent directories if needed.
    """
    existing = load_manual_keywords(path)
    if keyword in existing:
        raise ValueError(f"Keyword '{keyword}' already exists in {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(keyword + "\n")


def remove_keyword(keyword: str, path: Path) -> None:
    """Remove keyword from .interests file.

    Raises KeyError if keyword is not found.
    """
    existing = load_manual_keywords(path)
    if keyword not in existing:
        raise KeyError(f"Keyword '{keyword}' not found in {path}")
    existing.remove(keyword)
    save_manual_keywords(existing, path)


def purge_keyword(keyword: str, vault_path: Path) -> list[str]:
    """Delete all .md files in vault_path containing keyword (as [[wikilink]] or raw text).

    Returns list of deleted file paths.
    """
    deleted = []
    for md_file in vault_path.rglob("*.md"):
        content = md_file.read_text()
        if keyword in content or f"[[{keyword}]]" in content:
            md_file.unlink()
            deleted.append(str(md_file))
    return deleted
