import sys
import os
from pathlib import Path

# Ensure the parent directory is in sys.path so we can import from personalWiki modules
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from mcp.server.fastmcp import FastMCP
from config import VAULT_PATH
from core.keywords_manager import load_manual_keywords
from pathlib import Path

_KEYWORDS_FILE = Path(VAULT_PATH) / "_keywords"

# Create an MCP server named "personalWiki"
mcp = FastMCP("personalWiki")

@mcp.tool()
def search_vault_notes(query: str, limit: int = 5) -> str:
    """
    Search vault note keys — title, ticker, company, author, date, type,
    keywords and tags. Note bodies are not indexed.
    """
    try:
        import frontmatter
        from core.bm25_index import bm25_search

        results = bm25_search(query, top_k=limit)

        if not results:
            return "No notes found matching the query."

        formatted_str = f"Found {len(results)} results:\n\n"
        for i, r in enumerate(results, 1):
            path = r["path"]
            try:
                metadata = frontmatter.load(path).metadata
            except Exception:
                metadata = {}
            title = metadata.get("title") or metadata.get("company") or "Untitled"

            formatted_str += f"{i}. {title}\n"
            formatted_str += f"   Path: {path}\n"
            formatted_str += f"   Score: {r['score']:.3f}\n"
            formatted_str += "\n"

        return formatted_str
    except Exception as e:
        return f"Search failed: {e}"

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

@mcp.tool()
def get_about_vlad() -> str:
    """
    Get structured summary of what the LLM knows about Vlad.
    Includes projects, investments, ideas, preferences.
    """
    try:
        from core.vector_store import get_store

        store = get_store()
        results = store.search_entities("Vlad projects investments preferences", top_k=10)
        if not results:
            return "No personal context found."
        formatted = "About Vlad:\n\n"
        for r in results:
            formatted += f"- [{r.get('entity_type','unknown')}] {r.get('entity_name','?')}: {r.get('summary','')[:200]}\n"
        return formatted
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
def get_project_context(project_name: str) -> str:
    """
    Get all knowledge about a specific project by name.
    """
    try:
        from core.vector_store import get_store

        store = get_store()
        results = store.search_entities(project_name, entity_type="project", top_k=5)
        if not results:
            return f"No project found matching '{project_name}'."
        formatted = f"Project: {project_name}\n\n"
        for r in results:
            formatted += f"{r.get('summary','')[:500]}\n\n"
        return formatted
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
def get_recent(max_results: int = 5) -> str:
    """
    Get recently indexed knowledge from the vault.
    """
    try:
        from core.vector_store import get_store

        store = get_store()
        results = store.get_recent_notes(top_k=max_results)
        if not results:
            return "No recent notes found."
        formatted = f"Recent {len(results)} notes:\n\n"
        for r in results:
            title = r.get("metadata", {}).get("title", "Untitled")
            formatted += f"- {title}\n"
        return formatted
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    # Start the MCP server using stdio transport (the default for FastMCP run)
    mcp.run()
