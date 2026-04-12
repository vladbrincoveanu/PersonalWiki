from datetime import date
import frontmatter
from config import NOTES_DIR


def upsert_entity_notes(entities: list[dict]) -> None:
    """Create stub notes for entities that don't yet exist. Never overwrites."""
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        slug = entity.get("slug", "")
        name = entity.get("name", "")
        entity_type = entity.get("type", "concept")
        if not slug or not name:
            continue
        filepath = NOTES_DIR / f"{slug}.md"
        if not filepath.resolve().is_relative_to(NOTES_DIR.resolve()):
            continue
        if filepath.exists():
            continue
        metadata = {
            "title": name,
            "type": entity_type,
            "tags": [],
            "created": str(date.today()),
        }
        post = frontmatter.Post("_Not filled in yet._", **metadata)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(frontmatter.dumps(post))
