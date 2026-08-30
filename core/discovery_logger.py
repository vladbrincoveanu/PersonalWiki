"""Discovery activity logger — ring buffer of events persisted to JSON."""
import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

_LOG_DIR = Path.home() / ".personalWiki"
_LOG_FILE = _LOG_DIR / "discovery_activity.json"
_MAX_EVENTS = 500

EventStatus = Literal["enqueued", "ingested", "failed"]


def _today() -> str:
    return date.today().isoformat()


class DiscoveryEvent(dict):
    """A discovery activity event. Stored as a dict for JSON serialization."""

    def __init__(
        self,
        url: str,
        title: str | None,
        source: str,
        status: EventStatus,
        discovered_at: str | None = None,
        ingested_at: str | None = None,
        error: str | None = None,
    ):
        super().__init__()
        self["url"] = url
        self["title"] = title or _domain_from_url(url)
        self["source"] = source
        self["status"] = status
        self["discovered_at"] = discovered_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self["ingested_at"] = ingested_at
        self["error"] = error

    @property
    def url(self) -> str:
        return self["url"]

    @property
    def title(self) -> str | None:
        return self.get("title")

    @property
    def source(self) -> str:
        return self["source"]

    @property
    def status(self) -> EventStatus:
        return self["status"]

    @property
    def discovered_at(self) -> str:
        return self["discovered_at"]

    @property
    def ingested_at(self) -> str | None:
        return self.get("ingested_at")

    @property
    def error(self) -> str | None:
        return self.get("error")


def _domain_from_url(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc
    except Exception:
        return url


class DiscoveryLogger:
    """Ring buffer of discovery events, persisted to JSON."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[DiscoveryEvent] = []
        self._load()

    def _load(self) -> None:
        """Load events from disk, keep last _MAX_EVENTS."""
        try:
            if _LOG_FILE.exists():
                with open(_LOG_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._events = [DiscoveryEvent(**e) for e in raw[-_MAX_EVENTS:]]
        except Exception:
            self._events = []

    def _persist(self) -> None:
        """Write events to disk (last _MAX_EVENTS only)."""
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump([dict(e) for e in self._events[-_MAX_EVENTS:]], f, indent=2)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("DiscoveryLogger: persist failed: %s", exc)

    def record(
        self,
        url: str,
        title: str | None,
        source: str,
        status: EventStatus,
        error: str | None = None,
    ) -> None:
        """Record a new discovery event. Skips if URL already has a pending event."""
        with self._lock:
            if status == "enqueued":
                for e in reversed(self._events):
                    if e.get("url") == url and e.get("status") == "enqueued":
                        return
            event = DiscoveryEvent(
                url=url,
                title=title,
                source=source,
                status=status,
                error=error,
            )
            self._events.append(event)
            if len(self._events) > _MAX_EVENTS:
                self._events = self._events[-_MAX_EVENTS:]
            self._persist()

    def update_status(
        self,
        url: str,
        status: EventStatus,
        error: str | None = None,
    ) -> None:
        """Update the status of the most recent event for a URL."""
        with self._lock:
            for event in reversed(self._events):
                if event["url"] == url:
                    event["status"] = status
                    if status == "ingested":
                        event["ingested_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    if error:
                        event["error"] = error
                    break
            self._persist()

    def today(self) -> list[DiscoveryEvent]:
        """Return all events from today."""
        today_str = _today()
        with self._lock:
            result = []
            for e in self._events:
                discovered_at = getattr(e, "discovered_at", None) or e.get("discovered_at") if isinstance(e, dict) else None
                if discovered_at and discovered_at.startswith(today_str):
                    result.append(e)
            return result

    def stats(self) -> dict:
        """Return today's stats."""
        events = self.today()
        def get_status(e: DiscoveryEvent) -> EventStatus:
            return getattr(e, "status", None) or e.get("status") if isinstance(e, dict) else None
        return {
            "discovered_today": len(events),
            "ingested_today": sum(1 for e in events if get_status(e) == "ingested"),
            "failed_today": sum(1 for e in events if get_status(e) == "failed"),
            "queue_depth": sum(1 for e in events if get_status(e) == "enqueued"),
            "last_cycle_at": events[-1]["discovered_at"] if events else None,
        }

    def clear(self) -> None:
        """Clear all events from memory and disk."""
        with self._lock:
            self._events.clear()
            try:
                _LOG_FILE.write_text("[]", encoding="utf-8")
            except Exception:
                pass


# Singleton instance
_logger: DiscoveryLogger | None = None
_logger_lock = threading.Lock()


def get_discovery_logger() -> DiscoveryLogger:
    """Get the singleton DiscoveryLogger instance."""
    global _logger
    if _logger is None:
        with _logger_lock:
            if _logger is None:
                _logger = DiscoveryLogger()
    return _logger
