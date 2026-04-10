import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

VAULT_PATH = Path(os.getenv("VAULT_PATH", "/Users/vladbrincoveanu/Documents/ObsidianVault"))
NOTES_DIR = VAULT_PATH / "notes"
INDEX_PATH = Path(os.getenv("INDEX_PATH", "./.vke_index"))

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_GROUP_ID = os.getenv("MINIMAX_GROUP_ID", "")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "abab6.5s-chat")
MINIMAX_API_URL = "https://api.minimax.chat/v1/text/chatcompletion_v2"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
TOP_K_SIMILAR = 3
MAX_EMBED_CHARS = 2000
