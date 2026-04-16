import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

VAULT_PATH = Path(os.getenv("VAULT_PATH", "/Users/vladbrincoveanu/Library/Mobile Documents/iCloud~md~obsidian/Documents/PersonalWiki"))
NOTES_DIR = VAULT_PATH / "notes"
INDEX_PATH = Path(os.getenv("INDEX_PATH", "./.vke_index"))

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_GROUP_ID = os.getenv("MINIMAX_GROUP_ID", "")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7-HighSpeed")
MINIMAX_API_URL = "https://api.minimax.io/v1/text/chatcompletion_v2"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
TOP_K_SIMILAR = 3
MAX_EMBED_CHARS = 2000

# Autonomous discovery
DISCOVERY_ENABLED = os.getenv("DISCOVERY_ENABLED", "true").lower() == "true"
DISCOVERY_INTERVAL = int(os.getenv("DISCOVERY_INTERVAL", "3600"))
INTEREST_HUB_TOP_K = int(os.getenv("INTEREST_HUB_TOP_K", "15"))
INTEREST_LEAF_TOP_K = int(os.getenv("INTEREST_LEAF_TOP_K", "10"))
INTEREST_REFRESH_INTERVAL = int(os.getenv("INTEREST_REFRESH_INTERVAL", "21600"))
MAX_URLS_PER_CYCLE = int(os.getenv("MAX_URLS_PER_CYCLE", "10"))
