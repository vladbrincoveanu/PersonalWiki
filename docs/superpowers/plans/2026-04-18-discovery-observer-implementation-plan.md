# Discovery Observer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Visibility into the autonomous discovery system: mark discovered notes with provenance, record all attempts, show live stats+feed in the UI, and write a daily digest note.

**Architecture:** DiscoveryLogger is the central event log. Scheduler emits events at each stage. write_note gains an is_discovery flag. A new API endpoint serves activity. The UI sidebar shows stats and feed.

**Tech Stack:** Python asyncio, FastAPI, existing vault/writer.py, existing discovery_scheduler.py

---

## File Map

- Create: `core/discovery_logger.py` — DiscoveryLogger class
- Create: `core/digest_writer.py` — Daily digest note writer
- Modify: `vault/writer.py` — is_discovery flag, notes/discovered/, frontmatter+tag
- Modify: `pipeline.py` — pass is_discovery to write_note
- Modify: `core/discovery_scheduler.py` — emit events to DiscoveryLogger
- Modify: `app.py` — GET /api/discovery/activity endpoint
- Modify: `templates/index.html` — Discovery panel in sidebar
- Test: `tests/test_discovery_logger.py` — DiscoveryLogger unit tests
- Test: `tests/test_discovery_writer.py` — provenance unit tests
- Test: `tests/test_digest_writer.py` — digest writer unit tests
- Test: `tests/test_discovery_integration.py` — API integration test

---

## Task 1: DiscoveryLogger core

**Files:**
- Create: `core/discovery_logger.py`
- Test: `tests/test_discovery_logger.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_logger.py
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

def test_discovery_event_dataclass():
    """DiscoveryEvent stores all fields correctly."""
    from core.discovery_logger import DiscoveryEvent
    from datetime import datetime

    event = DiscoveryEvent(
        url="https://pytorch.org/blog/25",
        title="PyTorch 2.5",
        source="sitemap: pytorch.org",
        status="ingested",
        discovered_at="2026-04-18T10:00:00Z",
        ingested_at="2026-04-18T10:01:00Z",
        error=None,
    )
    assert event.url == "https://pytorch.org/blog/25"
    assert event.status == "ingested"
    assert event.title == "PyTorch 2.5"


def test_discovery_logger_records_event(tmp_path):
    """Logger records a discovery event."""
    from core.discovery_logger import DiscoveryLogger

    with patch("core.discovery_logger._LOG_FILE", tmp_path / "log.json"):
        logger = DiscoveryLogger()
        logger.record("https://example.com/article", "Example Article", "sitemap: example.com", "enqueued")

        events = logger.today()
        assert len(events) == 1
        assert events[0].url == "https://example.com/article"
        assert events[0].title == "Example Article"
        assert events[0].status == "enqueued"


def test_discovery_logger_updates_status(tmp_path):
    """Logger can update an existing event's status."""
    from core.discovery_logger import DiscoveryLogger

    with patch("core.discovery_logger._LOG_FILE", tmp_path / "log.json"):
        logger = DiscoveryLogger()
        logger.record("https://example.com/article", "Example", "sitemap: example.com", "enqueued")
        logger.update_status("https://example.com/article", "ingested")

        events = logger.today()
        assert events[0].status == "ingested"
        assert events[0].ingested_at is not None


def test_discovery_logger_stats(tmp_path):
    """Logger computes today's stats correctly."""
    from core.discovery_logger import DiscoveryLogger

    with patch("core.discovery_logger._LOG_FILE", tmp_path / "log.json"):
        logger = DiscoveryLogger()
        logger.record("https://a.com/1", "A", "sitemap: a.com", "enqueued")
        logger.record("https://b.com/2", "B", "keyword: test", "enqueued")
        logger.update_status("https://a.com/1", "ingested")
        logger.update_status("https://b.com/2", "failed", error="Quality gate rejected")

        stats = logger.stats()
        assert stats["discovered_today"] == 2
        assert stats["ingested_today"] == 1
        assert stats["failed_today"] == 1


def test_discovery_logger_today_only(tmp_path):
    """Logger returns only today's events."""
    from core.discovery_logger import DiscoveryLogger

    with patch("core.discovery_logger._LOG_FILE", tmp_path / "log.json"):
        logger = DiscoveryLogger()
        # Record a yesterday event manually
        yesterday = {
            "url": "https://old.com/article",
            "title": "Old Article",
            "source": "sitemap: old.com",
            "status": "ingested",
            "discovered_at": "2026-04-17T10:00:00Z",
            "ingested_at": "2026-04-17T10:01:00Z",
            "error": None,
        }
        logger._events.append(yesterday)
        logger._persist()

        # Only today should appear
        events = logger.today()
        assert all(e["discovered_at"].startswith("2026-04-18") for e in events)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_discovery_logger.py -v`
Expected: FAIL — core.discovery_logger does not exist

- [ ] **Step 3: Implement DiscoveryLogger**

Create `core/discovery_logger.py`:

```python
"""Discovery activity logger — ring buffer of events persisted to JSON."""
import json
import threading
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from config import VAULT_PATH

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
        self["discovered_at"] = discovered_at or datetime.utcnow().isoformat() + "Z"
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
        """Write events to disk."""
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump([dict(e) for e in self._events], f, indent=2)
        except Exception:
            pass

    def record(
        self,
        url: str,
        title: str | None,
        source: str,
        status: EventStatus,
        error: str | None = None,
    ) -> None:
        """Record a new discovery event."""
        with self._lock:
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
                        event["ingested_at"] = datetime.utcnow().isoformat() + "Z"
                    if error:
                        event["error"] = error
                    break
            self._persist()

    def today(self) -> list[DiscoveryEvent]:
        """Return all events from today."""
        today_str = _today()
        with self._lock:
            return [e for e in self._events if e.discovered_at.startswith(today_str)]

    def stats(self) -> dict:
        """Return today's stats."""
        events = self.today()
        return {
            "discovered_today": len(events),
            "ingested_today": sum(1 for e in events if e.status == "ingested"),
            "failed_today": sum(1 for e in events if e.status == "failed"),
            "queue_depth": sum(1 for e in events if e.status == "enqueued"),
            "last_cycle_at": events[-1]["discovered_at"] if events else None,
        }


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_discovery_logger.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/discovery_logger.py tests/test_discovery_logger.py
git commit -m "feat: add DiscoveryLogger with ring buffer and JSON persistence"
```

---

## Task 2: write_note provenance (is_discovery flag)

**Files:**
- Modify: `vault/writer.py:273-316`
- Test: `tests/test_discovery_writer.py` (new file)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_writer.py
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

def test_write_note_is_discovery_routes_to_discovered_folder(tmp_path):
    """Discovered notes go to notes/discovered/."""
    from vault.writer import write_note

    notes_dir = tmp_path / "notes"
    discovered_dir = tmp_path / "notes" / "discovered"
    with (
        patch("vault.writer.NOTES_DIR", notes_dir),
        patch("vault.writer.VAULT_PATH", tmp_path),
    ):
        notes_dir.mkdir(parents=True, exist_ok=True)
        discovered_dir.mkdir(parents=True, exist_ok=True)

        path = write_note(
            {"title": "Test Discovery Note", "type": "article", "summary": "A test note.", "key_facts": [], "raw_text": "Full content here."},
            source="https://example.com/test",
            is_discovery=True,
        )

        assert "discovered" in path
        assert Path(path).exists()

def test_write_note_is_discovery_adds_frontmatter(tmp_path):
    """Discovered notes have discovery: auto in frontmatter."""
    from vault.writer import write_note
    import frontmatter

    notes_dir = tmp_path / "notes"
    discovered_dir = tmp_path / "notes" / "discovered"
    with (
        patch("vault.writer.NOTES_DIR", notes_dir),
        patch("vault.writer.VAULT_PATH", tmp_path),
    ):
        notes_dir.mkdir(parents=True, exist_ok=True)
        discovered_dir.mkdir(parents=True, exist_ok=True)

        path = write_note(
            {"title": "Test Discovery Note", "type": "article", "summary": "A test note.", "key_facts": [], "raw_text": "Full content here."},
            source="https://example.com/test",
            is_discovery=True,
        )

        post = frontmatter.load(path)
        assert post.metadata.get("discovery") == "auto"

def test_write_note_is_discovery_false_unchanged(tmp_path):
    """Manual notes (is_discovery=False) are unchanged."""
    from vault.writer import write_note
    import frontmatter

    notes_dir = tmp_path / "notes"
    with (
        patch("vault.writer.NOTES_DIR", notes_dir),
        patch("vault.writer.VAULT_PATH", tmp_path),
    ):
        notes_dir.mkdir(parents=True, exist_ok=True)

        path = write_note(
            {"title": "Manual Note", "type": "article", "summary": "A manual note.", "key_facts": [], "raw_text": "Full content here."},
            source="https://example.com/manual",
            is_discovery=False,
        )

        post = frontmatter.load(path)
        assert "discovery" not in post.metadata
        assert "discovered" not in path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_discovery_writer.py -v`
Expected: FAIL — write_note doesn't accept is_discovery param

- [ ] **Step 3: Modify write_note**

**Change the signature (line ~273):**
```python
def write_note(
    note: dict,
    source: str,
    ingested_date: str | None = None,
    images: Sequence[bytes] = (),
    entity_statuses: list[dict] = (),
    is_discovery: bool = False,
) -> str:
```

**Change the path logic (lines ~280-292):**
```python
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    title = note.get("title") or "Untitled"
    ingested_date = ingested_date or str(date.today())
    slug = slugify(title)

    # Discovered notes go to notes/discovered/, others to notes/
    if is_discovery:
        notes_subdir = NOTES_DIR / "discovered"
    else:
        notes_subdir = NOTES_DIR
    notes_subdir.mkdir(parents=True, exist_ok=True)

    filepath = notes_subdir / f"{slug}.md"
```

**Change the frontmatter (lines ~294-300):**
```python
    metadata = {
        "title": title,
        "source": source,
        "type": note.get("type", "article"),
        "tags": [t for raw in (note.get("tags") or []) if (t := _clean_tag(raw))],
        "ingested": ingested_date,
    }

    if is_discovery:
        metadata["discovery"] = "auto"
```

**Add the body tag (after `body = _build_body(...)` around line ~310):**
```python
    if is_discovery:
        body = body.rstrip() + "\n\n#auto-discovery\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_discovery_writer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vault/writer.py tests/test_discovery_writer.py
git commit -m "feat: add is_discovery provenance to write_note"
```

---

## Task 3: Pipeline passes is_discovery to write_note

**Files:**
- Modify: `pipeline.py:79-85, 197-201`
- Test: existing tests

- [ ] **Step 1: Add is_discovery param to run_pipeline**

Change the `run_pipeline` signature (line ~79):
```python
async def run_pipeline(
    url: str | None = None,
    pdf_path: str | None = None,
    docx_path: str | None = None,
    md_path: str | None = None,
    txt_path: str | None = None,
    is_discovery: bool = False,
) -> AsyncGenerator[str, None]:
```

Change the write_note call (line ~199):
```python
    path = write_note(
        note, source=source, images=images, entity_statuses=entity_statuses,
        is_discovery=is_discovery,
    )
```

- [ ] **Step 2: Run existing tests to verify they pass**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (default is_discovery=False preserves existing behavior)

- [ ] **Step 3: Commit**

```bash
git add pipeline.py
git commit -m "feat: pipeline accepts is_discovery flag"
```

---

## Task 4: Scheduler emits events to DiscoveryLogger

**Files:**
- Modify: `core/discovery_scheduler.py` — _run_pipeline, _enqueue_interest_domain
- Test: existing tests

- [ ] **Step 1: Add import at top of file**

After existing imports (around line 38):
```python
from core.discovery_logger import get_discovery_logger
```

- [ ] **Step 2: Add event emission to _enqueue_interest_domain**

In `_enqueue_interest_domain` (around line 310), after `self._sitemap_queue.put_nowait(url)` add:
```python
                dl_logger = get_discovery_logger()
                dl_logger.record(url, None, f"sitemap: {domain}", "enqueued")
```

Also add after the domain enqueue log line (~line 303):
```python
        dl_logger = get_discovery_logger()
        dl_logger.record(f"https://{domain}", None, f"domain: {domain}", "enqueued")
```

- [ ] **Step 3: Update _run_pipeline to emit ingested/failed events**

Replace `_run_pipeline` method (lines ~764-771):
```python
    async def _run_pipeline(self, url: str) -> None:
        """Run ingestion pipeline for a single URL."""
        dl_logger = get_discovery_logger()
        try:
            from pipeline import run_pipeline
            async for _ in run_pipeline(url=url, is_discovery=True):
                pass
            dl_logger.update_status(url, "ingested")
        except Exception as e:
            dl_logger.update_status(url, "failed", error=str(e))
            _logger.error("Discovery: pipeline failed for %s: %s", url, e)
```

- [ ] **Step 4: Run existing tests to verify they pass**

Run: `pytest tests/test_discovery_scheduler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/discovery_scheduler.py
git commit -m "feat: scheduler emits discovery events to DiscoveryLogger"
```

---

## Task 5: Daily digest note writer

**Files:**
- Create: `core/digest_writer.py`
- Modify: `core/discovery_scheduler.py` — call digest writer at end of cycle
- Test: `tests/test_digest_writer.py` (new file)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_digest_writer.py
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

def test_write_digest_creates_discovery_folder(tmp_path):
    """Digest note is written to Discovery/ folder."""
    from core.digest_writer import write_daily_digest

    discovery_dir = tmp_path / "Discovery"
    with patch("core.digest_writer.DISCOVERY_DIR", discovery_dir):
        discovery_dir.mkdir(parents=True, exist_ok=True)

        events = [
            {
                "url": "https://pytorch.org/blog/25",
                "title": "PyTorch 2.5 Released",
                "source": "sitemap: pytorch.org",
                "status": "ingested",
                "discovered_at": "2026-04-18T10:00:00Z",
                "ingested_at": "2026-04-18T10:01:00Z",
                "error": None,
            }
        ]

        path = write_daily_digest(events, date_str="2026-04-18")
        assert Path(path).exists()
        assert "2026-04-18" in path


def test_digest_note_contains_events(tmp_path):
    """Digest note lists all events."""
    from core.digest_writer import write_daily_digest

    discovery_dir = tmp_path / "Discovery"
    with patch("core.digest_writer.DISCOVERY_DIR", discovery_dir):
        discovery_dir.mkdir(parents=True, exist_ok=True)

        events = [
            {
                "url": "https://pytorch.org/blog/25",
                "title": "PyTorch 2.5",
                "source": "sitemap: pytorch.org",
                "status": "ingested",
                "discovered_at": "2026-04-18T10:00:00Z",
                "ingested_at": "2026-04-18T10:01:00Z",
                "error": None,
            },
            {
                "url": "https://example.com/old",
                "title": "Old Post",
                "source": "sitemap: example.com",
                "status": "failed",
                "discovered_at": "2026-04-18T10:00:00Z",
                "ingested_at": None,
                "error": "Quality gate rejected",
            },
        ]

        path = write_daily_digest(events, date_str="2026-04-18")
        content = Path(path).read_text()
        assert "PyTorch 2.5" in content
        assert "Old Post" in content
        assert "pytorch.org" in content
        assert "2026-04-18" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_digest_writer.py -v`
Expected: FAIL — core.digest_writer does not exist

- [ ] **Step 3: Implement digest_writer**

Create `core/digest_writer.py`:

```python
"""Daily discovery digest note writer."""
from pathlib import Path

from config import VAULT_PATH

DISCOVERY_DIR = VAULT_PATH / "Discovery"


def write_daily_digest(events: list[dict], date_str: str) -> str:
    """Write or update a daily discovery digest note.

    Events should be today's DiscoveryEvent dicts.
    """
    DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    filepath = DISCOVERY_DIR / f"{date_str}.md"

    ingested = [e for e in events if e["status"] == "ingested"]
    failed = [e for e in events if e["status"] == "failed"]

    lines = [
        "---",
        f"title: Discovery Digest — {date_str}",
        "tags: #auto-discovery #daily-digest",
        "---",
        "",
        f"## Discovery Activity — {date_str}",
        "",
        "### Summary",
        f"- **{len(events)}** URLs attempted",
        f"- **{len(ingested)}** ingested",
        f"- **{len(failed)}** failed",
        "",
    ]

    if ingested:
        lines.append("### Ingested")
        lines.append("")
        lines.append("| Source | Title |")
        lines.append("|--------|-------|")
        for e in ingested:
            domain = ""
            if ":" in (e.get("source") or ""):
                domain = e.get("source", "").split(": ", 1)[1]
            title = e.get("title") or e.get("url", "")
            lines.append(f"| {domain} | {title} |")
        lines.append("")

    if failed:
        lines.append("### Failed")
        lines.append("")
        lines.append("| Source | URL | Error |")
        lines.append("|--------|-----|-------|")
        for e in failed:
            domain = ""
            if ":" in (e.get("source") or ""):
                domain = e.get("source", "").split(": ", 1)[1]
            error = e.get("error") or ""
            lines.append(f"| {domain} | {e.get('url', '')} | {error} |")
        lines.append("")

    content = "\n".join(lines)

    if filepath.exists():
        filepath.write_text(content, encoding="utf-8")
    else:
        filepath.write_text(content, encoding="utf-8")

    return str(filepath)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_digest_writer.py -v`
Expected: PASS

- [ ] **Step 5: Wire digest writer into scheduler**

In `_run_discovery_cycle` (around line 730, after `self._persist_seen_urls()`), add:
```python
        # Write daily digest
        from core.digest_writer import write_daily_digest
        from datetime import date
        today_str = date.today().isoformat()
        events = get_discovery_logger().today()
        if events:
            write_daily_digest([dict(e) for e in events], today_str)
```

- [ ] **Step 6: Commit**

```bash
git add core/digest_writer.py core/discovery_scheduler.py tests/test_digest_writer.py
git commit -m "feat: add daily digest note writer"
```

---

## Task 6: API endpoint /api/discovery/activity

**Files:**
- Modify: `app.py` — add GET /api/discovery/activity
- Test: `tests/test_discovery_integration.py` — add API test

- [ ] **Step 1: Write the failing test**

In `tests/test_discovery_integration.py`, add:
```python
@pytest.mark.asyncio
async def test_discovery_activity_api():
    """GET /api/discovery/activity returns today's events and stats."""
    from unittest.mock import patch, MagicMock
    from fastapi.testclient import TestClient
    from app import app

    with patch("core.discovery_logger.get_discovery_logger") as mock_logger:
        mock_instance = MagicMock()
        mock_instance.stats.return_value = {
            "discovered_today": 3,
            "ingested_today": 2,
            "failed_today": 1,
            "queue_depth": 0,
            "last_cycle_at": "2026-04-18T10:00:00Z",
        }
        mock_instance.today.return_value = [
            {
                "url": "https://pytorch.org/blog",
                "title": "PyTorch Blog",
                "source": "sitemap: pytorch.org",
                "status": "ingested",
                "discovered_at": "2026-04-18T10:00:00Z",
                "ingested_at": "2026-04-18T10:01:00Z",
                "error": None,
            }
        ]
        mock_logger.return_value = mock_instance

        client = TestClient(app)
        response = client.get("/api/discovery/activity")

        assert response.status_code == 200
        data = response.json()
        assert data["stats"]["discovered_today"] == 3
        assert len(data["events"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_integration.py::test_discovery_activity_api -v`
Expected: FAIL — route doesn't exist

- [ ] **Step 3: Add endpoint to app.py**

Add after the `/keywords` endpoints (around line 172):
```python
@app.get("/api/discovery/activity")
async def get_discovery_activity():
    """Return today's discovery activity: stats and events."""
    from core.discovery_logger import get_discovery_logger
    logger = get_discovery_logger()
    return {
        "stats": logger.stats(),
        "events": [dict(e) for e in logger.today()],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_discovery_integration.py::test_discovery_activity_api -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_discovery_integration.py
git commit -m "feat: add /api/discovery/activity endpoint"
```

---

## Task 7: Web UI Discovery panel

**Files:**
- Modify: `templates/index.html`
- Test: manual verification

- [ ] **Step 1: Read the current index.html to find the sidebar section**

Run: `grep -n "right\|sidebar\|panel" templates/index.html | head -20`
Read the section around the right panel/sidebar.

- [ ] **Step 2: Add Discovery panel HTML**

Find the right panel area in `templates/index.html`. Add the Discovery panel inside the main layout, after the upload form area. Read the file to find the exact insertion point.

Add this HTML (adapt to your existing structure):
```html
        <!-- Discovery Panel -->
        <div id="discovery-panel" class="discovery-panel">
          <div class="discovery-header">
            <h3>🔍 Discovery</h3>
            <button onclick="loadDiscoveryActivity()" class="refresh-btn" title="Refresh">↻</button>
          </div>
          <div id="discovery-stats" class="discovery-stats">
            <span>—</span>
          </div>
          <div id="discovery-feed" class="discovery-feed">
            <div class="discovery-empty">No discovery activity today.</div>
          </div>
        </div>
```

- [ ] **Step 3: Add CSS for Discovery panel**

Add to the `<style>` section:
```css
/* Discovery panel */
.discovery-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem;
  margin-top: 1rem;
}

.discovery-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.discovery-header h3 {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text);
}

.discovery-stats {
  display: flex;
  gap: 1rem;
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-bottom: 0.75rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border);
}

.discovery-stat {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.discovery-stat .num {
  color: var(--text);
  font-weight: 600;
}

.discovery-feed {
  max-height: 300px;
  overflow-y: auto;
}

.discovery-item {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.4rem 0;
  border-bottom: 1px solid var(--surface-2);
  font-size: 0.8rem;
}

.discovery-item:last-child {
  border-bottom: none;
}

.discovery-badge {
  flex-shrink: 0;
  font-size: 0.7rem;
  padding: 0.1rem 0.3rem;
  border-radius: 4px;
  font-weight: 600;
}

.badge-ingested { background: var(--accent-dim); color: var(--accent); }
.badge-failed { background: var(--danger-dim); color: var(--danger); }
.badge-pending { background: var(--surface-3); color: var(--text-muted); }

.discovery-item-content {
  flex: 1;
  min-width: 0;
}

.discovery-item-title {
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
}

.discovery-item-domain {
  color: var(--text-dim);
  font-size: 0.7rem;
}

.discovery-empty {
  color: var(--text-dim);
  font-size: 0.8rem;
  text-align: center;
  padding: 1rem;
}
```

- [ ] **Step 4: Add JavaScript to fetch and render discovery activity**

Add to the `<script>` section at the bottom. Use DOM methods (createElement, textContent) instead of innerHTML for security:

```javascript
async function loadDiscoveryActivity() {
  try {
    const res = await fetch('/api/discovery/activity');
    if (!res.ok) return;
    const data = await res.json();
    renderDiscoveryActivity(data);
  } catch (e) {
    console.warn('Discovery activity load failed:', e);
  }
}

function renderDiscoveryActivity(data) {
  const stats = data.stats || {};
  const events = data.events || [];

  // Render stats
  const statsEl = document.getElementById('discovery-stats');
  if (statsEl) {
    let lastCycle = '—';
    if (stats.last_cycle_at) {
      try {
        lastCycle = new Date(stats.last_cycle_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      } catch (e) {
        lastCycle = '—';
      }
    }
    statsEl.innerHTML = '';
    const s1 = document.createElement('span');
    s1.className = 'discovery-stat';
    s1.innerHTML = `<span class="num">${stats.discovered_today || 0}</span> today`;
    const s2 = document.createElement('span');
    s2.className = 'discovery-stat';
    s2.innerHTML = `<span class="num">${stats.queue_depth || 0}</span> queue`;
    const s3 = document.createElement('span');
    s3.className = 'discovery-stat';
    s3.textContent = lastCycle;
    statsEl.appendChild(s1);
    statsEl.appendChild(s2);
    statsEl.appendChild(s3);
  }

  // Render feed using DOM methods (no innerHTML with user data)
  const feedEl = document.getElementById('discovery-feed');
  if (!feedEl) return;

  feedEl.innerHTML = '';
  if (events.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'discovery-empty';
    empty.textContent = 'No discovery activity today.';
    feedEl.appendChild(empty);
    return;
  }

  const reversed = events.slice().reverse();
  reversed.forEach(function(event) {
    const item = document.createElement('div');
    item.className = 'discovery-item';

    const badge = document.createElement('span');
    badge.className = 'discovery-badge';
    if (event.status === 'ingested') {
      badge.classList.add('badge-ingested');
      badge.textContent = '✅';
    } else if (event.status === 'failed') {
      badge.classList.add('badge-failed');
      badge.textContent = '❌';
    } else {
      badge.classList.add('badge-pending');
      badge.textContent = '⏳';
    }

    const content = document.createElement('div');
    content.className = 'discovery-item-content';

    const link = document.createElement('a');
    link.href = event.url || '#';
    link.target = '_blank';
    link.className = 'discovery-item-title';
    link.title = event.url || '';
    link.textContent = event.title || event.url || '';

    const domain = document.createElement('span');
    domain.className = 'discovery-item-domain';
    const sourceParts = (event.source || '').split(': ');
    domain.textContent = sourceParts[sourceParts.length - 1] || '';

    content.appendChild(link);
    content.appendChild(domain);
    item.appendChild(badge);
    item.appendChild(content);
    feedEl.appendChild(item);
  });
}

// Load on page load and every 30 seconds
document.addEventListener('DOMContentLoaded', loadDiscoveryActivity);
setInterval(loadDiscoveryActivity, 30000);
```

- [ ] **Step 5: Verify**

Run: `python app.py` and check http://localhost:8000 — the Discovery panel should appear.

- [ ] **Step 6: Commit**

```bash
git add templates/index.html
git commit -m "feat: add Discovery panel to web UI"
```

---

## Spec Coverage Check

| Spec requirement | Task |
|----------------|------|
| DiscoveryLogger ring buffer | Task 1 |
| Provenance frontmatter + notes/discovered/ | Task 2 |
| is_discovery through pipeline | Task 3 |
| Scheduler emits events | Task 4 |
| Daily digest note | Task 5 |
| /api/discovery/activity endpoint | Task 6 |
| Web UI Discovery panel | Task 7 |

All spec requirements covered. No gaps.
