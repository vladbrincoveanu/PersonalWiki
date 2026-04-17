from pathlib import Path
from ingesters import Document


def extract_markdown(path: str | Path) -> Document:
    """Extract text content from a Markdown or plain text file."""
    doc_path = Path(path)
    text = doc_path.read_text(encoding="utf-8")
    return Document(raw_text=text, content_type="document")
