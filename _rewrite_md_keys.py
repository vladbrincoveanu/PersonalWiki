import os
import re
from pathlib import Path
from config import VAULT_PATH
from core.minimax_client import enrich
from vault.writer import write_note
from core.vector_store import get_store
from core.embeddings import embed
from config import MAX_EMBED_CHARS
import time

notes_dir = Path(VAULT_PATH) / "notes"

def extract_raw_text(content: str) -> str:
    # Match raw section with details/summary
    match = re.search(r"<summary>Original extracted text</summary>\n(.*)</details>", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"## Raw Extract\n(.*)", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Fallback: remove frontmatter and return the rest
    match = re.match(r"^---\n.*?\n---\n(.*)", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return content

def rewrite_all():
    store = get_store()
    for file in notes_dir.glob("*.md"):
        print(f"Processing {file.name}...")
        try:
            with open(file, "r", encoding="utf-8") as f:
                content = f.read()
                
            raw_text = extract_raw_text(content)
            if not raw_text:
                print(f"Skipping {file.name} (no text found)")
                continue
                
            # Get existing source if possible from frontmatter
            source = file.stem 
            source_match = re.search(r"^source:\s*(.*)$", content, re.MULTILINE)
            if source_match:
                source = source_match.group(1).strip()

            # Find similar
            vector = embed(raw_text[:MAX_EMBED_CHARS])
            similar = store.search(vector, top_k=3)
            similar_titles = [
                s["metadata"].get("title", Path(s["path"]).stem)
                for s in similar if isinstance(s.get("metadata"), dict)
            ]
            
            # Enrich
            note = enrich(raw_text, similar_titles, source)
            if note.get("error"):
                print(f"Error enriching {file.name}, skipping.")
                continue
            
            # Preserve the same file name so we don't break existing links unexpectedly.
            # To do that, we can temporarily hack the title or simply overwrite the file manually
            # But the user might want the title to be English as well!
            # So let's use write_note, and if the slug changes, we delete the old file.
            
            new_path = write_note(note, source=source)
            
            index_meta = {k: v for k, v in note.items() if k != "raw_text"}
            index_meta["_file_path"] = new_path
            store.upsert(
                path=source,
                text=raw_text,
                vector=vector,
                links=note.get("cross_links", []),
                metadata=index_meta,
            )
            
            new_path_abs = Path(new_path).absolute()
            old_path_abs = file.absolute()
            if new_path_abs != old_path_abs:
                os.remove(old_path_abs)
                print(f"Renamed {file.name} -> {Path(new_path).name}")
            else:
                print(f"Updated {file.name}")
            
            time.sleep(1) # Simple rate limit protection for MiniMax API
            
        except Exception as e:
            print(f"Failed processing {file.name}: {e}")

if __name__ == "__main__":
    rewrite_all()
