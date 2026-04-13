"""
Extracts interest keywords from the vault graph.
Hub nodes (high connectivity) and leaf nodes (specialized topics) become search keywords.
"""
import re
import os
from pathlib import Path
from config import VAULT_PATH, INTEREST_HUB_TOP_K, INTEREST_LEAF_TOP_K


def _parse_wikilinks(text: str) -> list[str]:
    """Return list of note titles linked via [[wikilink]]."""
    return re.findall(r"\[\[([^\]]+)\]\]", text)


def _note_title_from_content(content: str) -> str:
    """Extract H1 title from markdown content, or 'Untitled'."""
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return "Untitled"


def _scan_vault(vault_path: str | Path) -> dict[str, dict]:
    """
    Scan vault .md files. Returns dict:
      title -> {"inbound": set(), "outbound": set()}
    """
    vault = Path(vault_path)
    nodes: dict[str, dict] = {}

    for md_file in vault.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        title = _note_title_from_content(content)
        outbound = set(_parse_wikilinks(content))

        if title not in nodes:
            nodes[title] = {"inbound": set(), "outbound": set()}
        nodes[title]["outbound"].update(outbound)

        for linked in outbound:
            if linked not in nodes:
                nodes[linked] = {"inbound": set(), "outbound": set()}
            nodes[linked]["inbound"].add(title)

    return nodes


def _extract_tags(vault_path: str | Path) -> list[str]:
    """Extract unique tags from all vault frontmatter."""
    import frontmatter
    tags: set[str] = set()
    vault = Path(vault_path)
    for md_file in vault.rglob("*.md"):
        try:
            post = frontmatter.load(md_file)
            tags.update(post.get("tags", []))
        except Exception:
            continue
    return [t for t in tags if t]


def extract_interests(vault_path: str | Path | None = None) -> list[str]:
    """
    Returns deduplicated list of interest keyword strings.
    Derived from hub score (inbound+outbound) and leaf score (outbound only),
    plus frontmatter tags.
    """
    if vault_path is None:
        vault_path = os.environ.get("VAULT_PATH", str(VAULT_PATH))

    nodes = _scan_vault(vault_path)
    tags = _extract_tags(vault_path)

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

    # deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for kw in hub_keywords + leaf_keywords + tags:
        if kw not in seen:
            seen.add(kw)
            result.append(kw)
    return result
