import re
from datetime import date
from pathlib import Path
import frontmatter
from config import NOTES_DIR

def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug

def write_note(note: dict, source: str, ingested_date: str | None = None) -> str:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    title = note.get("title") or "Untitled"
    ingested_date = ingested_date or str(date.today())
    slug = slugify(title)
    filepath = NOTES_DIR / f"{slug}.md"

    # Handle slug collisions
    counter = 1
    while filepath.exists():
        filepath = NOTES_DIR / f"{slug}-{counter}.md"
        counter += 1

    metadata = {
        "title": title,
        "source": source,
        "type": note.get("type", "article"),
        "tags": note.get("tags", []),
        "ingested": ingested_date,
    }
    if note.get("error"):
        metadata["confidence"] = "low"

    cross_links = note.get("cross_links", [])
    cross_links_section = ""
    if cross_links:
        links_str = ", ".join(f"[[{l}]]" for l in cross_links)
        cross_links_section = f"\n## My Knowledge Says\n{links_str}\n"

    key_facts = note.get("key_facts", [])
    facts_str = "\n".join(f"- {f}" for f in key_facts) if key_facts else "_None extracted._"

    raw_text = note.get("raw_text", "")
    raw_section = f"\n## Raw Extract\n<details>\n<summary>Original extracted text</summary>\n\n{raw_text}\n\n</details>"

    body = f"""## Summary
{note.get('summary', '_Not available._')}

## Key Facts
{facts_str}
{cross_links_section}{raw_section}"""

    post = frontmatter.Post(body, **metadata)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))

    return str(filepath)
