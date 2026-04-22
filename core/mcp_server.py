import sys
import os
from pathlib import Path

# Ensure the parent directory is in sys.path so we can import from personalWiki modules
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from mcp.server.fastmcp import FastMCP
from config import VAULT_PATH
from core.vector_store import get_store
from core.keywords_manager import load_manual_keywords
from pathlib import Path

_KEYWORDS_FILE = Path(VAULT_PATH) / "_keywords"

# Create an MCP server named "personalWiki"
mcp = FastMCP("personalWiki")

@mcp.tool()
def search_vault_notes(query: str, limit: int = 5) -> str:
    """
    Search the personalWiki hybrid vector/BM25/Graph knowledge base for notes.
    Use this to find relevant notes based on semantic meaning or keywords.
    """
    try:
        store = get_store()
        results = store.hybrid_search(query, top_k=limit)

        if not results:
            return "No notes found matching the query."

        # Simplify the results so LLM isn't flooded with raw vectors
        formatted_str = f"Found {len(results)} results:\n\n"
        for i, r in enumerate(results, 1):
            path = r.get("path", "Unknown path")
            score = r.get("score", 0.0)
            metadata = r.get("metadata", {})
            title = metadata.get("title", "Untitled")

            formatted_str += f"{i}. {title}\n"
            formatted_str += f"   Path: {path}\n"
            formatted_str += f"   Score: {score:.3f}\n"
            if "summary" in metadata:
                summary = metadata["summary"]
                # trunc if needed, but since it's a short summary it should be fine
                formatted_str += f"   Summary: {summary}\n"
            formatted_str += "\n"

        return formatted_str
    except Exception as e:
        return f"Error during search: {e}"

@mcp.tool()
def read_note_content(path: str) -> str:
    """
    Read the full raw markdown content of a specific note given its absolute path or relative vault path.
    Use this after getting relevant note paths from search_vault_notes to read the full context.
    """
    p_path = Path(path)
    if not p_path.is_absolute():
        val_path = Path(os.environ.get("VAULT_PATH", VAULT_PATH))
        p_path = val_path / p_path

    if not p_path.exists():
        return f"File not found: {p_path}"

    try:
        content = p_path.read_text(encoding="utf-8")
        return f"--- File: {p_path} ---\n\n{content}"
    except Exception as e:
        return f"Error reading file: {e}"

@mcp.tool()
def get_vault_graph_interests() -> str:
    """
    Get the current list of keywords from the vault keywords file.
    This helps understand what topics are actively tracked in the vault.
    Returns a comma-separated list of keywords.
    """
    try:
        keywords = load_manual_keywords(_KEYWORDS_FILE)
        if not keywords:
            return "No keywords found."
        return f"Active keywords:\n{', '.join(keywords)}"
    except Exception as e:
        return f"Error reading keywords: {e}"

if __name__ == "__main__":
    # Start the MCP server using stdio transport (the default for FastMCP run)
    mcp.run()
