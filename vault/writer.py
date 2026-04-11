import re
from datetime import date
from pathlib import Path
import frontmatter
from config import NOTES_DIR, VAULT_PATH


def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug


def _save_images(images: list[bytes], slug: str) -> None:
    images_dir = VAULT_PATH / "attachments" / slug
    images_dir.mkdir(parents=True, exist_ok=True)
    for i, png_bytes in enumerate(images, start=1):
        (images_dir / f"figure-{i}.png").write_bytes(png_bytes)


def _replace_image_placeholders(text: str, slug: str, count: int) -> str:
    result = text
    for i in range(1, count + 1):
        result = result.replace(
            "<!-- image -->",
            f"![[attachments/{slug}/figure-{i}.png]]",
            1,
        )
    return result


def write_note(
    note: dict,
    source: str,
    ingested_date: str | None = None,
    images: list[bytes] = (),
) -> str:
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
    # Use the final slug (with counter if collided) for image directory
    final_slug = filepath.stem

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
    if images:
        _save_images(images, final_slug)
        raw_text = _replace_image_placeholders(raw_text, final_slug, len(images))

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
