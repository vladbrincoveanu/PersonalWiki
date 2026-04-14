"""
Post-enrichment entity gap detection.
Finds entities referenced in a note but not yet in the vault.
"""
import os
import re
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def _build_vault_index(vault_path: Path) -> tuple[set[str], set[str]]:
    """Build index of all slugs and titles in vault. One vault scan."""
    slugs: set[str] = set()
    titles: set[str] = set()
    for md_file in vault_path.rglob("*.md"):
        # Normalize slug: dashes and underscores are equivalent
        slugs.add(md_file.stem.lower().replace("_", "-"))
        try:
            content = md_file.read_text(encoding="utf-8")
            m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            if m:
                titles.add(m.group(1).strip().lower())
        except Exception:
            pass
    return slugs, titles


def detect_gaps(note_entities: list[dict], vault_path: str | Path | None = None) -> list[str]:
    """
    Returns list of entity names that are referenced in the enriched note
    but don't have corresponding notes in the vault.
    """
    if vault_path is None:
        vault_path = Path(os.environ.get("VAULT_PATH", ""))
    else:
        vault_path = Path(vault_path)

    if not vault_path.exists():
        _logger.warning("Vault path does not exist: %s", vault_path)
        return [e["name"] for e in note_entities if e.get("name")]

    # Build index once
    slug_index, title_index = _build_vault_index(vault_path)

    missing = []
    for entity in note_entities:
        name = entity.get("name", "")
        slug = entity.get("slug", name.lower().replace(" ", "-")).lower().replace(" ", "-")
        if not name:
            continue
        # Normalize slug: dashes and underscores are equivalent
        slug_normalized = slug.replace("_", "-")
        slug_in_vault = slug_normalized in slug_index or name.lower() in title_index
        if not slug_in_vault:
            missing.append(name)
    return missing
