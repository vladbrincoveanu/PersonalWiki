"""
Extracts interest keywords from the vault graph.
Hub nodes (high connectivity) and leaf nodes (specialized topics) become search keywords.
Keywords are validated via LLM to ensure they are good web search topics.
"""
import asyncio
import json
import logging
import re
import os
from pathlib import Path
import requests
from config import VAULT_PATH, INTEREST_HUB_TOP_K, INTEREST_LEAF_TOP_K, MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_API_URL


def _load_suppressed_for_extract(keywords_file: Path) -> set[str]:
    """Load suppressed keywords for extract_interests (called in-thread, no circular deps)."""
    suppressed_file = keywords_file.parent / (keywords_file.name + "-suppressed")
    if not suppressed_file.exists():
        return set()
    return {
        line.strip()
        for line in suppressed_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

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
    "attachments",
})


def _is_noise_keyword(kw: str) -> bool:
    """Return True if keyword is uninformative noise (orphan pages, generic titles, etc.)."""
    stripped = kw.strip().lower()
    if not stripped:
        return True
    if stripped in _NOISE_KEYWORDS:
        return True
    return False


async def _filter_keywords_via_llm(candidates: list[str]) -> list[str]:
    """
    Ask the LLM to validate which candidates are good web search topics.
    Returns a filtered list of keywords that are specific enough to find relevant content.
    Falls back to returning all candidates on failure.
    """
    if not candidates or not MINIMAX_API_KEY:
        return candidates

    prompt = (
        "You are a research topic validator. Given a list of candidate keywords from a personal knowledge graph,\n"
        "return the subset that are SPECIFIC TOPICS worth searching the web for.\n\n"
        "RULES:\n"
        "- Accept: proper research topics, technologies, methods, company/product names, field names,\n"
        "  person names, dataset names, and concepts that appear in academic/technical content.\n"
        "- Accept note titles that look like meaningful topics (even if short, e.g. 'RLHF', 'LLaMA', 'k8s').\n"
        "- Reject ONLY: clearly non-topics like '404', 'page not found', 'readme', 'untitled',\n"
        "  'index', attachment paths, numeric IDs without meaning, or strings that are just symbols.\n"
        "- Be permissive: when in doubt, include the keyword. It's better to have extra topics\n"
        "  than to miss valid ones.\n\n"
        f"Candidates ({len(candidates)} total):\n" +
        "\n".join(f"- {kw}" for kw in candidates[:50]) +
        "\n\nReturn a JSON array of ACCEPTED keywords (max 30). Be permissive — include most candidates."
    )

    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MINIMAX_MODEL,
        "messages": [
            {"role": "system", "content": "You are a strict topic validator. Return valid JSON array only."},
            {"role": "user", "content": prompt},
        ],
    }

    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, lambda: requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=30))
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        decoder = json.JSONDecoder()
        validated, _ = decoder.raw_decode(content)
        if isinstance(validated, list) and all(isinstance(k, str) for k in validated):
            _logger.info("LLM filtered %d candidates -> %d validated", len(candidates), len(validated))
            return validated
    except Exception as e:
        _logger.warning("LLM keyword filter failed: %s — using all candidates", e)

    return candidates


def _parse_wikilinks(text: str) -> list[str]:
    """Return list of note titles linked via [[wikilink]], stripping pipe syntax.

    Filters out attachment paths (images, files in attachments/ folder).
    """
    # Strip pipe syntax: [[B|Display B]] -> B
    raw = re.findall(r"\[\[([^\]]+)\]\]", text)
    result = []
    for link in raw:
        title = link.split("|", 1)[0].strip()
        # Skip attachment paths (images, PDFs, etc.)
        if title.lower().startswith("attachments/"):
            continue
        if "/" in title or "\\" in title:
            continue
        # Skip obvious file references with extensions
        if re.search(r"\.(png|jpg|jpeg|gif|webp|pdf|svg|mp3|mp4)$", title, re.I):
            continue
        result.append(title)
    return result


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
    Returns deduplicated list of interest keyword strings (sync, blocking).
    Derived from hub score (inbound+outbound) and leaf score (outbound only),
    plus frontmatter tags. Noise keywords are filtered. Candidates are then
    validated via LLM to ensure they are good web search topics.

    Note: for async callers, prefer extract_interests_async() to avoid nested loops.
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
    candidates: list[str] = []
    for kw in hub_keywords + leaf_keywords + tags:
        if kw in seen or _is_noise_keyword(kw):
            continue
        seen.add(kw)
        candidates.append(kw)

    # LLM validation: ask which candidates are good web search topics
    # Also filter against suppressed blocklist
    keywords_file = Path(vault_path) / "_keywords" if isinstance(vault_path, str) else vault_path / "_keywords"
    suppressed = _load_suppressed_for_extract(keywords_file)

    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_filter_keywords_via_llm(candidates))
        loop.close()
        # Filter out suppressed keywords from LLM result
        return [kw for kw in result if kw not in suppressed]
    except Exception as e:
        _logger.warning("LLM filter failed: %s — returning candidates (suppressed excluded)", e)
        return [kw for kw in candidates if kw not in suppressed]
