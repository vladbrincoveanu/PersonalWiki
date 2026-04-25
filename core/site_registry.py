import asyncio
import json
from pathlib import Path
from datetime import date

_REGISTRY_PATH = Path.home() / ".personalWiki" / "site_registry.json"


class SiteRegistry:
    def __init__(self):
        self._domains: dict[str, dict] = {}
        self._pending_save = False
        self._save_lock = asyncio.Lock()
        self._load()

    def _load(self):
        if not _REGISTRY_PATH.exists():
            return
        try:
            with open(_REGISTRY_PATH) as f:
                self._domains = json.load(f).get("domains", {})
        except (json.JSONDecodeError, IOError):
            self._domains = {}

    def save(self):
        """Synchronous save - use sparingly. Prefer queue_save() in async contexts."""
        _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_REGISTRY_PATH, "w") as f:
            json.dump({"domains": self._domains}, f, indent=2)

    def add_domain(self, domain: str, source: str, url: str):
        if domain not in self._domains:
            self._domains[domain] = {
                "added_at": str(date.today()),
                "source": source,
                "last_sitemap_check": None,
                "known_urls": [],
            }
        if url and url not in self._domains[domain]["known_urls"]:
            self._domains[domain]["known_urls"].append(url)
        self.save()

    def add_url(self, domain: str, url: str):
        """Synchronous URL add - blocks on disk I/O. Use add_url_async() in async contexts."""
        if domain in self._domains and url not in self._domains[domain]["known_urls"]:
            self._domains[domain]["known_urls"].append(url)
            self.save()

    async def add_url_async(self, domain: str, url: str) -> None:
        """Async URL add with debounced save - does not block event loop."""
        if domain not in self._domains:
            return
        if url in self._domains[domain].get("known_urls", []):
            return

        self._domains[domain]["known_urls"].append(url)
        self._pending_save = True

        # Debounced save: wait for a quiet moment, then flush
        await asyncio.sleep(0.5)  # Wait for batching opportunities
        async with self._save_lock:
            if self._pending_save:
                await asyncio.to_thread(self.save)
                self._pending_save = False

    def is_known(self, domain: str) -> bool:
        return domain in self._domains

    def all_domains(self) -> list[str]:
        return list(self._domains.keys())

    def known_urls(self, domain: str) -> list[str]:
        return list(self._domains.get(domain, {}).get("known_urls", []))
