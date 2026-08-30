#!/usr/bin/env python3
"""One-time migration: rename tags frontmatter to keywords in all vault notes.

Also adds [[wikilink]] keywords section to notes that have keywords but no wikilink section.
"""
import re
from pathlib import Path
import frontmatter as fm


def migrate_note(filepath: Path) -> bool:
    """Migrate a single note. Returns True if changed."""
    raw = filepath.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return False

    parsed = fm.parse(raw)
    metadata, body = parsed

    if "keywords" in metadata:
        return False

    if "tags" not in metadata:
        return False

    keywords = metadata.pop("tags", [])
    metadata["keywords"] = keywords

    post = fm.Post(body, **metadata)
    filepath.write_text(fm.dumps(post), encoding="utf-8")

    if keywords and "## Keywords" not in body:
        raw = filepath.read_text(encoding="utf-8")
        links = " · ".join(f"[[{kw}]]" for kw in keywords)
        lines = raw.split("\n")
        insert_at = None
        for i, line in enumerate(lines):
            if line.startswith("## ") and not line.startswith("###"):
                insert_at = i + 1
                break
        if insert_at is not None:
            lines.insert(insert_at, f"\n## Keywords\n{links}")
            filepath.write_text("\n".join(lines), encoding="utf-8")

    return True


def main():
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config import VAULT_PATH

    migrated = 0
    errors = 0
    for md_file in sorted(VAULT_PATH.rglob("*.md")):
        try:
            if migrate_note(md_file):
                print(f"Migrated: {md_file.relative_to(VAULT_PATH)}")
                migrated += 1
        except Exception as e:
            print(f"Error migrating {md_file}: {e}")
            errors += 1

    print(f"\nDone. Migrated {migrated} notes, {errors} errors.")


if __name__ == "__main__":
    main()
