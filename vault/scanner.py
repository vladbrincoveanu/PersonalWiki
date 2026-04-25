import re
import frontmatter
from config import NOTES_DIR
from core.embeddings import embed
from core.vector_store import get_store

_WIKILINK_RE = re.compile(r'\[\[([^\]|#]+)(?:[|\#][^\]]*)?\]\]')


def parse_wikilinks(text: str) -> list[str]:
    return list(dict.fromkeys(_WIKILINK_RE.findall(text)))


def scan_vault() -> int:
    store = get_store()
    if not NOTES_DIR.exists():
        return 0

    indexed = 0
    for md_file in NOTES_DIR.glob("*.md"):
        file_mtime = md_file.stat().st_mtime
        stored_mtime = float(store.get_mtime(str(md_file)) or 0.0)
        if stored_mtime >= file_mtime:
            continue  # unchanged

        post = frontmatter.load(md_file)
        full_text = frontmatter.dumps(post)
        links = parse_wikilinks(full_text)
        metadata = dict(post.metadata)
        metadata["_mtime"] = file_mtime

        vector = embed(full_text[:2000])
        store.upsert(
            path=str(md_file),
            text=full_text,
            vector=vector,
            links=links,
            metadata=metadata,
        )
        indexed += 1

    return indexed


if __name__ == "__main__":
    count = scan_vault()
    print(f"Indexed {count} notes.")
