import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
import frontmatter
from config import NOTES_DIR, VAULT_PATH
from vault.entity_status import _build_prose


_VALID_TAG_RE = re.compile(r"^[a-z0-9_-]{2,30}$")


def _clean_tag(tag: str) -> str | None:
    """Return a valid Obsidian tag string, or None if the tag is invalid."""
    tag = tag.strip().lower().lstrip("#")
    if _VALID_TAG_RE.match(tag):
        return tag
    return None


def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug


def _save_images(images: Sequence[bytes], slug: str) -> None:
    images_dir = VAULT_PATH / "attachments" / slug
    images_dir.mkdir(parents=True, exist_ok=True)
    for i, png_bytes in enumerate(images, start=1):
        (images_dir / f"figure-{i}.png").write_bytes(png_bytes)


def _replace_image_placeholders(
    text: str, slug: str, count: int, captions: Sequence[str] = ()
) -> str:
    result = text
    for i in range(1, count + 1):
        caption = captions[i - 1] if i - 1 < len(captions) else ""
        if caption:
            replacement = (
                f"*Figure {i}: {caption}.*\n![[attachments/{slug}/figure-{i}.png]]"
            )
        else:
            replacement = f"![[attachments/{slug}/figure-{i}.png]]"
        result = result.replace("<!-- image -->", replacement, 1)
    return result


def _build_body(note: dict, entity_statuses: list[dict] = ()) -> str:
    """Dispatcher — branches on note['type'] to the appropriate template builder."""
    note_type = note.get("type", "article")
    if note_type == "video":
        return _build_video_body(note)
    elif note_type == "paper":
        return _build_paper_body(note, entity_statuses=entity_statuses)
    else:
        # article or unknown — fall back to article template
        return _build_article_body(note, entity_statuses=entity_statuses)


def _build_video_body(note: dict) -> str:
    summary = note.get("summary", "_Not available._")

    # Timestamped chapters
    chapters = note.get("chapters", [])
    if chapters:
        chapters_lines = "\n".join(
            f"- [{c['time']}] {c['title']}" for c in chapters if c.get("time") and c.get("title")
        )
        chapters_section = f"\n## Timestamped Chapters\n{chapters_lines}\n"
    else:
        chapters_section = ""

    # Key quotes — accept both 'quotes' (old) and 'key_quotes' (MiniMax) field names
    key_quotes = note.get("key_quotes") or note.get("quotes", [])
    if key_quotes:
        quotes_lines = "\n".join(
            f"> \"{q.get('text', '')}\" — {q.get('speaker', 'Unknown')}"
            for q in key_quotes if q.get("text")
        )
        if quotes_lines:
            quotes_section = f"\n## Key Quotes\n{quotes_lines}\n"
        else:
            quotes_section = ""
    else:
        quotes_section = ""

    # Topics covered — accept both 'topics' (old) and 'topics_covered' (MiniMax) field names
    topics = note.get("topics_covered") or note.get("topics", [])
    if topics:
        topics_lines = "\n".join(f"- {t}" for t in topics)
        topics_section = f"\n## Topics Covered\n{topics_lines}\n"
    else:
        topics_section = ""

    # Why I saved this
    why_saved_hint = note.get("why_saved_hint", "")
    if why_saved_hint:
        why_saved_section = (
            f"\n## Why I Saved This\n> {why_saved_hint}\n\n_(edit this)_\n"
        )
    else:
        why_saved_section = ""

    # Transcript (selected sections) — wrapped in <details>
    raw_text = note.get("raw_text", "")
    if raw_text:
        raw_section = (
            f"\n## Transcript (Selected Sections)\n"
            f"<details>\n<summary>Full transcript</summary>\n\n{raw_text}\n\n</details>"
        )
    else:
        raw_section = ""

    body = (
        f"## Summary\n{summary}\n"
        f"{chapters_section}{quotes_section}{topics_section}{why_saved_section}{raw_section}"
    )
    return body


def _build_paper_body(note: dict, entity_statuses: list[dict] = ()) -> str:
    summary = note.get("summary", "_Not available._")

    # TL;DR
    tldr = note.get("tldr", "")
    if tldr:
        tldr_section = f"\n## TL;DR\n_{tldr}_\n"
    else:
        tldr_section = ""

    # Key Findings
    key_facts = note.get("key_facts", [])
    if key_facts:
        facts_str = "\n".join(f"- {f}" for f in key_facts)
    else:
        facts_str = "_None extracted._"
    key_findings_section = f"\n## Key Findings\n{facts_str}\n"

    # Method / Architecture
    method = note.get("method", "")
    if method:
        method_section = f"\n## Method / Architecture\n{method}\n"
    else:
        method_section = ""

    # Benchmarks
    benchmarks = note.get("benchmarks", "")
    if benchmarks:
        benchmarks_section = f"\n## Benchmarks\n{benchmarks}\n"
    else:
        benchmarks_section = ""

    # Related Entities (## Entities for backward compat with existing tests)
    entities = note.get("entities", [])
    if entities:
        links = " · ".join(
            f"[[{e['name']}]]" for e in entities if e.get("name") and e.get("slug")
        )
        if links:
            related_entities_section = f"\n## Entities\n{links}\n"
        else:
            related_entities_section = ""
    else:
        related_entities_section = ""

    # My Knowledge Says (cross-links)
    cross_links = note.get("cross_links", [])
    if cross_links:
        links_str = ", ".join(f"[[{l}]]" for l in cross_links)
        my_knowledge_section = f"\n## My Knowledge Says\n{links_str}\n"
    else:
        my_knowledge_section = ""

    # Why I Saved This
    why_saved_hint = note.get("why_saved_hint", "")
    if why_saved_hint:
        why_saved_section = (
            f"\n## Why I Saved This\n> {why_saved_hint}\n\n_(edit this)_\n"
        )
    else:
        why_saved_section = ""

    # Recent Developments
    recent_dev_section = ""
    if entity_statuses:
        prose = _build_prose(entity_statuses)
        if prose:
            recent_dev_section = f"\n## Recent Developments\n{prose}\n"

    # Raw Extract
    raw_text = note.get("raw_text", "")
    if raw_text:
        raw_section = (
            f"\n## Raw Extract\n"
            f"<details>\n<summary>Original extracted text</summary>\n\n{raw_text}\n\n</details>"
        )
    else:
        raw_section = ""

    body = (
        f"## Summary\n{summary}\n"
        f"{tldr_section}{key_findings_section}{method_section}{benchmarks_section}"
        f"{related_entities_section}{my_knowledge_section}{why_saved_section}{recent_dev_section}{raw_section}"
    )
    return body


def _build_article_body(note: dict, entity_statuses: list[dict] = ()) -> str:
    """Article template (backward compatible). entity_statuses is passed separately
    since it is a param of write_note(), not part of the note dict."""
    summary = note.get("summary", "_Not available._")

    # Key Facts
    key_facts = note.get("key_facts", [])
    facts_str = (
        "\n".join(f"- {f}" for f in key_facts) if key_facts else "_None extracted._"
    )

    # Entities section
    entities = note.get("entities", [])
    entities_section = ""
    if entities:
        links = " · ".join(
            f"[[{e['name']}]]" for e in entities if e.get("name") and e.get("slug")
        )
        if links:
            entities_section = f"\n## Entities\n{links}\n"

    # Why I Saved This
    why_saved_hint = note.get("why_saved_hint", "")
    why_saved_section = ""
    if why_saved_hint:
        why_saved_section = (
            f"\n## Why I Saved This\n> {why_saved_hint}\n\n_(edit this)_\n"
        )

    # Recent Developments
    recent_dev_section = ""
    if entity_statuses:
        prose = _build_prose(entity_statuses)
        if prose:
            recent_dev_section = f"\n## Recent Developments\n{prose}\n"

    # My Knowledge Says (cross-links)
    cross_links = note.get("cross_links", [])
    cross_links_section = ""
    if cross_links:
        links_str = ", ".join(f"[[{l}]]" for l in cross_links)
        cross_links_section = f"\n## My Knowledge Says\n{links_str}\n"

    # Raw Extract
    raw_text = note.get("raw_text", "")
    if raw_text:
        raw_section = (
            f"\n## Raw Extract\n"
            f"<details>\n<summary>Original extracted text</summary>\n\n{raw_text}\n\n</details>"
        )
    else:
        raw_section = ""

    body = (
        f"## Summary\n{summary}\n\n"
        f"## Key Facts\n{facts_str}\n"
        f"{entities_section}{why_saved_section}{recent_dev_section}{cross_links_section}{raw_section}"
    )
    return body


def write_note(
    note: dict,
    source: str,
    ingested_date: str | None = None,
    images: Sequence[bytes] = (),
    entity_statuses: list[dict] = (),
    is_discovery: bool = False,
) -> str:
    # Discovered notes go to notes/discovered/, others to notes/
    if is_discovery:
        notes_subdir = NOTES_DIR / "discovered"
    else:
        notes_subdir = NOTES_DIR
    notes_subdir.mkdir(parents=True, exist_ok=True)

    title = note.get("title") or "Untitled"
    ingested_date = ingested_date or str(date.today())
    slug = slugify(title)
    filepath = notes_subdir / f"{slug}.md"

    # Handle slug collisions
    counter = 1
    while filepath.exists():
        filepath = notes_subdir / f"{slug}-{counter}.md"
        counter += 1
    final_slug = filepath.stem

    metadata = {
        "title": title,
        "source": source,
        "type": note.get("type", "article"),
        "tags": [t for raw in (note.get("tags") or []) if (t := _clean_tag(raw))],
        "ingested": ingested_date,
    }
    if is_discovery:
        metadata["discovery"] = "auto"

    # Replace image placeholders before building body
    figure_captions = note.get("figure_captions", [])
    if images:
        _save_images(images, final_slug)
        note["raw_text"] = _replace_image_placeholders(
            note.get("raw_text", ""), final_slug, len(images), figure_captions
        )

    body = _build_body(note, entity_statuses=entity_statuses)
    if is_discovery:
        body = body.rstrip() + "\n\n#auto-discovery\n"

    post = frontmatter.Post(body, **metadata)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))

    return str(filepath)
