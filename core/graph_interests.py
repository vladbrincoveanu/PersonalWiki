"""
Extracts interest keywords from the vault graph.
Hub nodes (high connectivity) and leaf nodes (specialized topics) become search keywords.
"""
import logging
import re
import os
from pathlib import Path
from config import VAULT_PATH, INTEREST_HUB_TOP_K, INTEREST_LEAF_TOP_K

_logger = logging.getLogger(__name__)

# Keywords to exclude from interest extraction — covers common orphan/uninformative note titles
_NOISE_KEYWORDS: frozenset[str] = frozenset({
    "untitled",
    "404",
    "page not found",
    "index",
    "readme",
    "read me",
    "note",
    "notes",
    "new note",
    "new",
    "untitled note",
    "no title",
    "none",
    "undefined",
    "null",
})


def _is_noise_keyword(kw: str) -> bool:
    """Return True if keyword is uninformative noise (orphan pages, generic titles, etc.)."""
    stripped = kw.strip().lower()
    if not stripped:
        return True
    if stripped in _NOISE_KEYWORDS:
        return True
    # Reject single characters, pure numbers, or very short strings
    if len(stripped) <= 2:
        return True
    return False


def _parse_wikilinks(text: str) -> list[str]:
    """Return list of note titles linked via [[wikilink]], stripping pipe syntax."""
    # Strip pipe syntax: [[B|Display B]] -> B
    raw = re.findall(r"\[\[([^\]]+)\]\]", text)
    return [link.split("|", 1)[0].strip() for link in raw]


def _strip_frontmatter(content: str) -> str:
    """Strip YAML frontmatter from Obsidian markdown content."""
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            return content[end + 4 :]
    return content


def _note_title_from_content(content: str) -> str:
    """Extract H1 title from markdown content, or 'Untitled'."""
    stripped = _strip_frontmatter(content)
    m = re.search(r"^#\s+(.+)$", stripped, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return "Untitled"


def _scan_vault(vault_path: str | Path) -> tuple[dict[str, dict], list[str]]:
    """
    Scan vault .md files in a single pass. Returns:
      - nodes: title -> {"inbound": set(), "outbound": set()}
      - tags: list of unique frontmatter tags
    """
    import frontmatter

    vault = Path(vault_path)
    if not vault.is_dir():
        _logger.warning("Vault path is not a directory: %s", vault_path)
        return {}, []

    nodes: dict[str, dict] = {}
    tags: set[str] = set()

    for md_file in vault.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as e:
            _logger.warning("Failed to read %s: %s", md_file, e)
            continue

        try:
            post = frontmatter.load(md_file)
            tags.update(post.get("tags", []))
        except Exception as e:
            _logger.warning("Failed to parse frontmatter in %s: %s", md_file, e)

        title = _note_title_from_content(content)
        outbound = set(_parse_wikilinks(content))

        if title not in nodes:
            nodes[title] = {"inbound": set(), "outbound": set()}
        nodes[title]["outbound"].update(outbound)

        for linked in outbound:
            if linked not in nodes:
                nodes[linked] = {"inbound": set(), "outbound": set()}
            nodes[linked]["inbound"].add(title)

    return nodes, [t for t in tags if t]


def extract_interests(vault_path: str | Path | None = None) -> list[str]:
    """
    Returns deduplicated list of interest keyword strings.
    Derived from hub score (inbound+outbound) and leaf score (outbound only),
    plus frontmatter tags. Noise keywords (Untitled, 404, etc.) are filtered out.
    """
    if vault_path is None:
        vault_path = os.environ.get("VAULT_PATH", str(VAULT_PATH))

    nodes, tags = _scan_vault(vault_path)

    hub_nodes = sorted(
        nodes.items(),
        key=lambda x: len(x[1]["inbound"]) + len(x[1]["outbound"]),
        reverse=True,
    )
    leaf_nodes = sorted(
        nodes.items(),
        key=lambda x: len(x[1]["outbound"]),
        reverse=True,
    )

    hub_keywords = [t for t, _ in hub_nodes[:INTEREST_HUB_TOP_K]]
    leaf_keywords = [t for t, _ in leaf_nodes[:INTEREST_LEAF_TOP_K]]

    # deduplicate while preserving order, filter noise
    seen: set[str] = set()
    result: list[str] = []
    for kw in hub_keywords + leaf_keywords + tags:
        if kw in seen or _is_noise_keyword(kw):
            continue
        seen.add(kw)
        result.append(kw)
    return result
