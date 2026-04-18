# Discovery Observer — Design Spec

## Goal

Visibility into the autonomous discovery system: what it finds, what it ingests, and what fails. Notes found by the discoverer are clearly marked so they can be distinguished from manual ingestions in Obsidian.

## Problem

The discoverer runs on a timer but produces no visible output until a note lands in the vault — and even then there's no indication it came from discovery vs. manual ingest. No sense of "what it tried today" or "what queued up."

## Solution

Three-part system:

1. **DiscoveryLogger** — ring buffer of discovery events, persisted to JSON. All discovery stages emit events (discovered, enqueued, ingested, failed).
2. **Provenance frontmatter** — discovered notes get `discovery: auto` in frontmatter, saved to `notes/discovered/`, tagged `#auto-discovery`.
3. **UI + Daily Digest** — web UI shows live stats + feed; a daily digest note lists all attempts from that day.

---

## Module: DiscoveryLogger

**Responsibility:** Record discovery events and serve today's activity.

**Interface:**
- `DiscoveryLogger.record(url, title, source, status)` — record an event
- `DiscoveryLogger.today()` — all events from today
- `DiscoveryLogger.stats()` — `{discovered, ingested, failed, queue_depth}`

**Data model:**
```python
@dataclass
class DiscoveryEvent:
    url: str
    title: str | None      # title if known, else URL domain
    source: str            # e.g. "sitemap: pytorch.org" or "keyword: transformers"
    status: str             # "enqueued" | "ingested" | "failed" | "pending"
    discovered_at: str      # ISO timestamp
    ingested_at: str | None # ISO timestamp if status == ingested
    error: str | None      # error message if failed
```

**Persistence:** Ring buffer of last 500 events, written to `~/.personalWiki/discovery_activity.json` on each write and on startup.

**Storage:** `~/.personalWiki/discovery_activity.json`

---

## Module: Provenance in write_note

**Responsibility:** Mark discovered notes differently from manual ones.

**Changes to `write_note` signature:**
```python
def write_note(note, source, ingested_date=None, images=(), entity_statuses=(), is_discovery=False)
```

**When `is_discovery=True`:**
- Filepath goes to `notes/discovered/` instead of `notes/`
- Frontmatter adds `discovery: auto`
- Body gets `#auto-discovery` tag appended

**Existing behavior when `is_discovery=False` (default):** unchanged.

---

## Module: DiscoveryScheduler integration

**Responsibility:** Emit events to DiscoveryLogger at each discovery stage.

**Emission points:**
1. **Link discovered** → `DiscoveryLogger.record(url, None, f"link: {domain}", "enqueued")`
2. **Sitemap URL discovered** → `DiscoveryLogger.record(url, None, f"sitemap: {domain}", "enqueued")`
3. **Keyword result** → `DiscoveryLogger.record(url, None, f"keyword: {keyword}", "enqueued")`
4. **Pipeline success** → update status to `"ingested"` with timestamp
5. **Pipeline failure** → update status to `"failed"` with error

**Digest note write:** After each discovery cycle, if any events were recorded, append a digest entry to `Discovery/YYYY-MM-DD.md`. If it's the first cycle of a new day, create the file fresh.

---

## Module: Daily Digest Note

**Responsibility:** Permanent log of discovery activity per day in Obsidian.

**Location:** `Discovery/YYYY-MM-DD.md`

**Format:**
```markdown
---
title: Discovery Digest — April 18, 2026
tags: #auto-discovery #daily-digest
---

## Discovery Activity — April 18, 2026

### Summary
- **12** URLs attempted
- **9** ingested
- **3** failed

### Ingested

| Source | Title | Domain |
|--------|-------|--------|
| sitemap: pytorch.org | PyTorch 2.5 Released | pytorch.org |
| keyword: transformers | Attention Is All You Need | arxiv.org |

### Failed

| Source | URL | Error |
|--------|-----|-------|
| sitemap: example.com | https://example.com/old-post | Quality gate rejected |
```

**Trigger:** End of each discovery cycle. Append to today's digest. If file doesn't exist, create it.

---

## API: GET /api/discovery/activity

**Response:**
```json
{
  "stats": {
    "discovered_today": 12,
    "ingested_today": 9,
    "failed_today": 3,
    "queue_depth": 4,
    "last_cycle_at": "2026-04-18T14:23:00Z"
  },
  "events": [
    {
      "url": "https://pytorch.org/blog/...",
      "title": "PyTorch 2.5 Released",
      "source": "sitemap: pytorch.org",
      "status": "ingested",
      "discovered_at": "2026-04-18T14:20:00Z",
      "ingested_at": "2026-04-18T14:21:00Z",
      "error": null
    }
  ]
}
```

---

## Web UI: Discovery Panel

**Location:** Collapsible panel in the right sidebar of `index.html`.

**Layout:**

```
┌─ Discovery ──────────────────────┐
│ 🔍 12 today   ⏳ 4 queue   2h ago │
├─────────────────────────────────┤
│ ▼ Today                          │
│                                   │
│ ✅ PyTorch 2.5 Released    pytorch.org │
│ ✅ Attention Is All You Need arxiv.org │
│ ❌ old-post                example.com │
│ ⏳ new-transformer         pytorch.org │
└─────────────────────────────────┘
```

**Badge meanings:**
- 🔍 discovered (auto)
- 📎 manual ingest

**Status badges:**
- ✅ ingested
- ❌ failed
- ⏳ pending (in queue)

**Behavior:**
- On page load, fetch `/api/discovery/activity` and render
- SSE subscription for live updates (`/stream/discovery` — new endpoint)
- Clicking a row opens the vault note in a new tab

---

## Discovery Folder Structure

```
vault/notes/
  discovered/          ← discovered notes land here
    pytorch-25-released.md
    attention-is-all-you-need.md
  manual-note.md       ← user-uploaded notes unchanged
  ...

Discovery/             ← daily digest notes
  2026-04-18.md
  2026-04-17.md
```

---

## File Changes

| File | Change |
|------|--------|
| `core/discovery_logger.py` | New — DiscoveryLogger class, event ring buffer, JSON persistence |
| `vault/writer.py` | Add `is_discovery` param, `notes/discovered/` path, frontmatter + tag |
| `core/discovery_scheduler.py` | Import DiscoveryLogger, emit events at each stage |
| `app.py` | Add `GET /api/discovery/activity` endpoint, SSE stream endpoint |
| `templates/index.html` | Add Discovery panel sidebar with stats + feed |
| `pipeline.py` | Pass `is_discovery=True` when called from discovery scheduler |

---

## What This Does NOT Change

- `run_pipeline` interface (adds `is_discovery` param, optional)
- Quality gates — all discovery content still passes through existing gates
- Scheduler timer, interest extraction, keyword search behavior

---

## Testing

1. **Unit: DiscoveryLogger records and retrieves events** — mock disk I/O
2. **Unit: write_note with is_discovery=True** — verifies path, frontmatter, tag
3. **Integration: discovery cycle emits events** — seed scheduler, run cycle, verify events recorded
4. **API: /api/discovery/activity returns today's stats** — mock logger, assert JSON shape
5. **UI: Discovery panel renders** — Playwright test asserting stats and feed render
