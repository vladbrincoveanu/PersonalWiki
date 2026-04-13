import logging
import requests
from typing import Optional

_logger = logging.getLogger(__name__)

_LIBRARY_TYPES = {"library", "framework", "tool"}


def _is_library_entity(entity: dict) -> bool:
    """Return True if entity type is tool/library/framework."""
    if not isinstance(entity, dict):
        return False
    return entity.get("type", "").lower() in _LIBRARY_TYPES


def _search_library_status(name: str, slug: str) -> Optional[dict]:
    """
    Perform web search for library/tool/framework version and status.
    Uses GitHub API for GitHub-hosted projects, PyPI API otherwise.
    Returns None if nothing found.
    """
    github_api = f"https://api.github.com/repos/{slug}"
    try:
        resp = requests.get(
            github_api, timeout=5, headers={"Accept": "application/vnd.github.v3+json"}
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "version": data.get("tag_name", data.get("name", "")),
                "status": "actively maintained"
                if data.get("pushed_at")
                else "archived",
                "source": f"GitHub ({data.get('full_name', '')})",
            }
    except Exception as e:
        _logger.debug("GitHub search failed for %s: %s", slug, e)

    pypi_url = f"https://pypi.org/pypi/{slug}/json"
    try:
        resp = requests.get(pypi_url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            info = data.get("info", {})
            return {
                "version": info.get("version", ""),
                "status": "actively maintained" if not info.get("yanked") else "yanked",
                "source": "PyPI",
            }
    except Exception as e:
        _logger.debug("PyPI search failed for %s: %s", slug, e)

    return None


def fetch_entity_status(entities: list[dict]) -> list[dict]:
    """
    Filter entities to only tool/library/framework types and fetch their web status.
    Returns list of dicts: {name, slug, version, status, source}
    """
    results = []
    for entity in entities:
        if not _is_library_entity(entity):
            continue
        name = entity.get("name", "")
        slug = entity.get("slug", "")
        if not name or not slug:
            continue
        status = _search_library_status(name, slug)
        if status:
            results.append(
                {
                    "name": name,
                    "slug": slug,
                    **status,
                }
            )
    return results


def _build_prose(statuses: list[dict]) -> str:
    """Build a single prose paragraph from entity statuses."""
    if not statuses:
        return ""

    parts = []
    for s in statuses:
        part = f"**{s['name']}**"
        if s.get("version"):
            part += f" ({s['version']})"
        part += f" — {s['status']}"
        if s.get("source"):
            part += f" (source: {s['source']})"
        parts.append(part)

    if len(parts) == 1:
        return f"Recent development: {parts[0]}."
    return "Recent developments: " + "; ".join(parts) + "."
