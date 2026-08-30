"""Daily discovery digest note writer."""
from config import VAULT_PATH

DISCOVERY_DIR = VAULT_PATH / "Discovery"


def _esc(text: str) -> str:
    """Escape pipe characters for markdown table cells."""
    return str(text).replace("|", "&#124;")


def write_daily_digest(events: list[dict], date_str: str) -> str:
    """Write a daily discovery digest note.

    Events should be today's DiscoveryEvent dicts.
    """
    DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    filepath = DISCOVERY_DIR / f"{date_str}.md"

    ingested = [e for e in events if e["status"] == "ingested"]
    failed = [e for e in events if e["status"] == "failed"]

    lines = [
        "---",
        f"title: Discovery Digest — {date_str}",
        "tags: #auto-discovery #daily-digest",
        "---",
        "",
        f"## Discovery Activity — {date_str}",
        "",
        "### Summary",
        f"- **{len(events)}** URLs attempted",
        f"- **{len(ingested)}** ingested",
        f"- **{len(failed)}** failed",
        "",
    ]

    if ingested:
        lines.append("### Ingested")
        lines.append("")
        lines.append("| Source | Title | Domain |")
        lines.append("|--------|-------|--------|")
        for e in ingested:
            source = e.get("source") or ""
            domain = ""
            if ": " in source:
                domain = source.split(": ", 1)[1]
            title = _esc(e.get("title") or e.get("url", ""))
            lines.append(f"| {domain} | {title} |")
        lines.append("")

    if failed:
        lines.append("### Failed")
        lines.append("")
        lines.append("| Source | URL | Error |")
        lines.append("|--------|-----|-------|")
        for e in failed:
            source = e.get("source") or ""
            domain = ""
            if ": " in source:
                domain = source.split(": ", 1)[1]
            url = _esc(e.get("url") or "")
            error = _esc(e.get("error") or "")
            lines.append(f"| {domain} | {url} | {error} |")
        lines.append("")

    content = "\n".join(lines) + "\n"
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)
