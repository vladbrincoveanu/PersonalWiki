import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Proxy for YouTube extraction (when server IP is blocked by YouTube)
# SOCKS5:   socks5://user:pass@us5012.socks.nordhold.net:1080
# HTTPS:    https://user:pass@us5012.https.nordhold.net:89
YOUTUBE_PROXY = os.getenv("YOUTUBE_PROXY", "")

VAULT_PATH = Path(os.getenv("VAULT_PATH", "/Users/vladbrincoveanu/Library/Mobile Documents/iCloud~md~obsidian/Documents/PersonalWiki"))
NOTES_DIR = VAULT_PATH / "notes"
INDEX_PATH = Path(os.getenv("INDEX_PATH", "./.vke_index"))

# OpenAI-compatible chat completions endpoint (DeepInfra by default).
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepinfra.com/v1/openai")
LLM_API_URL = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash-0731")
LLM_VISION_MODEL = os.getenv("LLM_VISION_MODEL", "Qwen/Qwen3-VL-235B-A22B-Instruct")

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
