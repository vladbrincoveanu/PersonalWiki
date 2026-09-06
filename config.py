import os
from dataclasses import dataclass
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

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_GROUP_ID = os.getenv("MINIMAX_GROUP_ID", "")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
MINIMAX_API_URL = "https://api.minimax.io/v1/text/chatcompletion_v2"
MINIMAX_VISION_MODEL = os.getenv("MINIMAX_VISION_MODEL", "MiniMax-VL")

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


@dataclass(frozen=True)
class TelemetrySettings:
    sentry_dsn: str
    sentry_environment: str | None
    sentry_release: str | None
    service_name: str
    service_version: str | None
    resource_attributes: str
    otlp_endpoint: str
    otlp_headers: str
    traces_sampler: str
    traces_sampler_arg: str
    sdk_disabled: bool


def get_telemetry_settings() -> TelemetrySettings:
    def optional(name: str) -> str | None:
        value = os.getenv(name, "").strip()
        return value or None

    return TelemetrySettings(
        sentry_dsn=os.getenv("SENTRY_DSN", "").strip(),
        sentry_environment=optional("SENTRY_ENVIRONMENT"),
        sentry_release=optional("SENTRY_RELEASE"),
        service_name=os.getenv("OTEL_SERVICE_NAME", "personalwiki").strip() or "personalwiki",
        service_version=optional("OTEL_SERVICE_VERSION"),
        resource_attributes=os.getenv("OTEL_RESOURCE_ATTRIBUTES", "").strip(),
        otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip(),
        otlp_headers=os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "").strip(),
        traces_sampler=os.getenv(
            "OTEL_TRACES_SAMPLER", "parentbased_traceidratio"
        ).strip().lower(),
        traces_sampler_arg=os.getenv("OTEL_TRACES_SAMPLER_ARG", "0.1").strip() or "0.1",
        sdk_disabled=os.getenv("OTEL_SDK_DISABLED", "false").strip().lower() == "true",
    )
