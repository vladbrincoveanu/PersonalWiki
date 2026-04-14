# Keyword Manager — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a UI panel in the FastAPI web app for viewing, adding, and removing interest keywords. Manual keywords persist in `vault/.interests`. Removing a keyword triggers automatic purge of all vault files containing it.

**Architecture:** Keywords are stored in `vault/.interests` (one per line). A new `core/keywords_manager.py` module handles file I/O. `DiscoveryScheduler._refresh_keywords()` merges graph keywords with manual keywords. FastAPI exposes REST endpoints wired to HTMX UI.

**Tech Stack:** FastAPI, HTMX, `pathlib.Path`, `pathlib.Path.unlink()` for file deletion.

---

## File Map

```
core/keywords_manager.py              [NEW] Manual keyword file I/O: load, save, add, remove, purge
core/discovery_scheduler.py           [MODIFIED] integrate keywords_manager; add add_keyword/remove_keyword API
app.py                                [MODIFIED] add GET /keywords, POST /keywords/add, POST /keywords/remove
templates/index.html                  [MODIFIED] add Keywords UI panel
tests/test_keywords_manager.py        [NEW] unit tests for keywords_manager
tests/test_discovery_scheduler.py     [MODIFIED] add tests for keyword merge in _refresh_keywords
```

---

## Task 1: Keywords Manager Core

**Files:**
- Create: `core/keywords_manager.py`
- Test: `tests/test_keywords_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_keywords_manager.py
import pytest, tempfile, os
from pathlib import Path

def test_load_returns_empty_list_when_file_missing(tmp_path):
    from core.keywords_manager import load_manual_keywords
    result = load_manual_keywords(tmp_path / ".interests")
    assert result == []

def test_save_and_load_roundtrip(tmp_path):
    from core.keywords_manager import save_manual_keywords, load_manual_keywords
    path = tmp_path / ".interests"
    save_manual_keywords(["actiuni", "BVB"], path)
    result = load_manual_keywords(path)
    assert result == ["actiuni", "BVB"]

def test_add_keyword_appends_without_duplicates(tmp_path):
    from core.keywords_manager import save_manual_keywords, add_keyword
    path = tmp_path / ".interests"
    save_manual_keywords(["BVB"], path)
    add_keyword("actiuni", path)
    content = (path).read_text()
    assert "actiuni" in content
    assert "BVB" in content

def test_add_duplicate_raises(tmp_path):
    from core.keywords_manager import save_manual_keywords, add_keyword
    path = tmp_path / ".interests"
    save_manual_keywords(["BVB"], path)
    with pytest.raises(ValueError, match="already exists"):
        add_keyword("BVB", path)

def test_remove_keyword_deletes_from_file(tmp_path):
    from core.keywords_manager import save_manual_keywords, remove_keyword
    path = tmp_path / ".interests"
    save_manual_keywords(["BVB", "actiuni"], path)
    remove_keyword("BVB", path)
    result = load_manual_keywords(path)
    assert result == ["actiuni"]

def test_purge_deletes_files_containing_keyword(tmp_path):
    from core.keywords_manager import save_manual_keywords, purge_keyword
    vault = tmp_path / "notes"
    vault.mkdir()
    (vault / "bvb-note.md").write_text("# BVB\n[[BVB]]\nSome content about BVB.\n")
    (vault / "unrelated.md").write_text("# Unrelated\nThis has nothing.\n")
    path = tmp_path / ".interests"
    save_manual_keywords(["BVB"], path)
    purged = purge_keyword("BVB", vault)
    assert len(purged) == 1
    assert not (vault / "bvb-note.md").exists()
    assert (vault / "unrelated.md").exists()

def test_purge_matches_raw_text_not_just_wikilink(tmp_path):
    from core.keywords_manager import save_manual_keywords, purge_keyword
    vault = tmp_path / "notes"
    vault.mkdir()
    # File contains keyword in body text but not as wikilink
    (vault / "bursa-mention.md").write_text("# Mention\nThe word bursa appears here.\n")
    path = tmp_path / ".interests"
    save_manual_keywords(["burB"], path)  # "burB" won't match — let's use exact case
    purged = purge_keyword("bur", vault)
    assert len(purged) == 1
    assert not (vault / "bursa-mention.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_keywords_manager.py -v 2>&1 | head -20`
Expected: FAIL — module `core.keywords_manager` not found

- [ ] **Step 3: Write minimal implementation**

```python
# core/keywords_manager.py
"""
Manual interest keyword persistence in vault/.interests.
"""
from pathlib import Path


def load_manual_keywords(path: Path) -> list[str]:
    """Load keywords from .interests file. Returns empty list if file doesn't exist."""
    if not path.exists():
        return []
    keywords: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keywords.append(line)
    return keywords


def save_manual_keywords(keywords: list[str], path: Path) -> None:
    """Write keywords to .interests file, creating parent directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(keywords) + "\n"
    path.write_text(content, encoding="utf-8")


def add_keyword(keyword: str, path: Path) -> None:
    """Add a keyword to .interests. Raises ValueError if already present."""
    keywords = load_manual_keywords(path)
    if keyword in keywords:
        raise ValueError(f"Keyword already exists: {keyword}")
    keywords.append(keyword)
    save_manual_keywords(keywords, path)


def remove_keyword(keyword: str, path: Path) -> None:
    """Remove a keyword from .interests. Raises KeyError if not found."""
    keywords = load_manual_keywords(path)
    if keyword not in keywords:
        raise KeyError(f"Keyword not found: {keyword}")
    keywords.remove(keyword)
    save_manual_keywords(keywords, path)


def purge_keyword(keyword: str, vault_path: Path) -> list[str]:
    """
    Delete all .md files in vault_path that contain `keyword` (as [[wikilink]] or raw text).
    Returns list of deleted file paths as strings.
    """
    deleted: list[str] = []
    for md_file in vault_path.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            if keyword in content or f"[[{keyword}]]" in content:
                md_file.unlink()
                deleted.append(str(md_file))
        except Exception:
            continue
    return deleted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_keywords_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/keywords_manager.py tests/test_keywords_manager.py
git commit -m "feat: add keywords_manager for manual keyword persistence"
```

---

## Task 2: Integrate into DiscoveryScheduler

**Files:**
- Modify: `core/discovery_scheduler.py`

Read the existing file first to understand the current `_refresh_keywords` method.

- [ ] **Step 1: Add import and INTEREST_FILE path constant to discovery_scheduler.py**

After the existing imports (after `from config import (...)`), add:
```python
from config import VAULT_PATH
from core.keywords_manager import load_manual_keywords

INTERESTS_FILE = Path(VAULT_PATH) / ".interests"
```

- [ ] **Step 2: Modify `_refresh_keywords` to merge manual keywords**

Find the existing `_refresh_keywords` method. After:
```python
keywords = extract_interests()
self._keywords = keywords
```

Add:
```python
# Merge manual keywords from .interests
try:
    manual = load_manual_keywords(INTERESTS_FILE)
except Exception:
    manual = []
merged = list(dict.fromkeys(self._keywords + manual))
self._keywords = merged
_logger.info("Discovery: refreshed %d keywords (%d manual)", len(self._keywords), len(manual))
```

- [ ] **Step 3: Add `add_keyword` and `remove_keyword` convenience methods**

Add these methods to the `DiscoveryScheduler` class (after `stop` method):

```python
def add_keyword(self, keyword: str) -> None:
    """Add a manual keyword to .interests and immediately activate it."""
    add_keyword(keyword, INTERESTS_FILE)
    if keyword not in self._keywords:
        self._keywords.append(keyword)

def remove_keyword(self, keyword: str) -> list[str]:
    """Remove keyword from .interests and purge any vault files containing it. Returns purged file paths."""
    remove_keyword(keyword, INTERESTS_FILE)
    if keyword in self._keywords:
        self._keywords.remove(keyword)
    vault_path = Path(VAULT_PATH)
    return purge_keyword(keyword, vault_path)
```

Note: the module-level `add_keyword`, `remove_keyword`, `purge_keyword` imports from `keywords_manager` shadow the class method names — use different names for the class methods or import with alias.

Use alias approach:
```python
from core.keywords_manager import (
    load_manual_keywords as _load_manual_keywords,
    add_keyword as _km_add,
    remove_keyword as _km_remove,
    purge_keyword as _km_purge,
)
```

And in class methods:
```python
manual = _load_manual_keywords(INTERESTS_FILE)
```

- [ ] **Step 4: Write a test verifying merge**

```python
def test_refresh_keywords_includes_manual(tmp_path, monkeypatch):
    """_refresh_keywords merges graph keywords with manual .interests keywords."""
    from core.discovery_scheduler import DiscoveryScheduler

    # Create a minimal vault with one graph keyword
    vault = tmp_path / "notes"
    vault.mkdir()
    (vault / "graph-note.md").write_text("# Graph Note\n[[Other]]\n")

    # Create .interests with a manual keyword
    interests = tmp_path / ".interests"
    interests.write_text("manual-kw\n")

    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    scheduler = DiscoveryScheduler()
    import asyncio
    asyncio.get_event_loop().run_until_complete(scheduler._refresh_keywords())

    assert "manual-kw" in scheduler._keywords
```

- [ ] **Step 5: Run discovery scheduler tests**

Run: `pytest tests/test_discovery_scheduler.py -v`
Expected: PASS (all existing tests + new one)

- [ ] **Step 6: Commit**

```bash
git add core/discovery_scheduler.py tests/test_discovery_scheduler.py
git commit -m "feat: integrate manual keywords into DiscoveryScheduler"
```

---

## Task 3: REST API Endpoints

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Read existing app.py to find where to add endpoints**

After line 91 (after the `stream` endpoint), add:

```python
from fastapi import HTTPException

# Singleton scheduler instance for keyword operations
_scheduler: DiscoveryScheduler | None = None


def _get_scheduler() -> DiscoveryScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = DiscoveryScheduler()
    return _scheduler


@app.get("/keywords", response_model=dict)
async def get_keywords():
    """Return all active keywords with breakdown by source."""
    scheduler = _get_scheduler()
    graph_kw = []
    try:
        from core.graph_interests import extract_interests
        graph_kw = extract_interests()
    except Exception:
        pass
    manual = []
    try:
        from core.keywords_manager import load_manual_keywords
        from config import VAULT_PATH
        manual = load_manual_keywords(Path(VAULT_PATH) / ".interests")
    except Exception:
        pass
    all_kw = list(dict.fromkeys(graph_kw + manual))
    return {
        "keywords": all_kw,
        "manual": manual,
        "graph": graph_kw,
        "total": len(all_kw),
    }


@app.post("/keywords/add")
async def add_keyword_endpoint(keyword: str = Form(...)):
    """Add a manual keyword to .interests."""
    from core.keywords_manager import add_keyword as km_add
    from config import VAULT_PATH
    from pathlib import Path
    interests_path = Path(VAULT_PATH) / ".interests"
    try:
        km_add(keyword.strip(), interests_path)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    scheduler = _get_scheduler()
    if keyword.strip() not in scheduler._keywords:
        scheduler._keywords.append(keyword.strip())
    return {"added": keyword.strip()}


@app.post("/keywords/remove")
async def remove_keyword_endpoint(keyword: str = Form(...)):
    """Remove a keyword from .interests and purge vault files containing it."""
    from core.keywords_manager import remove_keyword as km_remove, purge_keyword
    from config import VAULT_PATH
    from pathlib import Path
    interests_path = Path(VAULT_PATH) / ".interests"
    vault_path = Path(VAULT_PATH)
    try:
        km_remove(keyword.strip(), interests_path)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Keyword not found: {keyword}")
    purged = purge_keyword(keyword.strip(), vault_path)
    scheduler = _get_scheduler()
    if keyword.strip() in scheduler._keywords:
        scheduler._keywords.remove(keyword.strip())
    return {"removed": keyword.strip(), "purged": purged, "purged_count": len(purged)}
```

Note: the scheduler lifespan handling needs care. The lifespan creates a scheduler and calls `scheduler.start()`. For the keyword API, we need a reference to the same scheduler instance. Use the module-level `_scheduler` singleton set in the lifespan.

- [ ] **Step 2: Update lifespan to register the scheduler instance**

In the `lifespan` function, after `scheduler = DiscoveryScheduler()`, add:
```python
    global _scheduler
    _scheduler = scheduler
```

- [ ] **Step 3: Test the endpoints manually**

Run: `python -c "from app import get_keywords; print('imports OK')"`

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: add keyword management REST API endpoints"
```

---

## Task 4: UI — Keywords Panel

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Add Keywords section HTML**

Add after the `#progress` div (line 121) and before the closing `</body>`:

```html
        <div class="card" style="margin-top: 1rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; cursor: pointer;"
                 onclick="document.getElementById('keywords-panel').classList.toggle('hidden')">
                <label style="margin: 0; cursor: pointer;">Keywords (<span id="kw-count">—</span>)</label>
                <span id="kw-toggle">▼</span>
            </div>
            <div id="keywords-panel" class="keywords-panel">
                <div id="kw-list" style="display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.75rem;"></div>
                <div style="display: flex; gap: 0.5rem; margin-top: 0.75rem;">
                    <input type="text" id="kw-input" placeholder="Add keyword..."
                           style="flex: 1; background: #111; border: 1px solid #333; border-radius: 6px;
                                  padding: 0.5rem 0.75rem; color: #e5e5e5; font-size: 0.85rem; outline: none;"
                           onkeydown="if(event.key==='Enter')addKeyword()">
                    <button onclick="addKeyword()" style="background: #6366f1; color: white; border: none;
                            border-radius: 6px; padding: 0.5rem 0.75rem; cursor: pointer; font-size: 0.85rem;">+</button>
                </div>
                <div id="kw-msg" style="margin-top: 0.5rem; font-size: 0.8rem; color: #a3e635;"></div>
            </div>
        </div>

        <style>
            .keywords-panel { margin-top: 0; }
            .keywords-panel.hidden { display: none; }
            .kw-chip {
                display: inline-flex; align-items: center; gap: 0.3rem;
                background: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 20px;
                padding: 0.25rem 0.6rem; font-size: 0.8rem; color: #ccc;
            }
            .kw-chip .del {
                background: none; border: none; color: #666; cursor: pointer;
                font-size: 0.9rem; line-height: 1; padding: 0; margin-left: 2px;
            }
            .kw-chip .del:hover { color: #ef4444; }
        </style>

        <script>
            async function loadKeywords() {
                const r = await fetch('/keywords');
                const data = await r.json();
                document.getElementById('kw-count').textContent = data.total;
                const list = document.getElementById('kw-list');
                list.innerHTML = '';
                for (const kw of data.keywords) {
                    const isManual = data.manual.includes(kw);
                    const chip = document.createElement('span');
                    chip.className = 'kw-chip';
                    chip.innerHTML = kw + (isManual
                        ? '<button class="del" onclick="removeKeyword(\'' + kw + '\')">✕</button>'
                        : '');
                    list.appendChild(chip);
                }
            }
            async function addKeyword() {
                const input = document.getElementById('kw-input');
                const kw = input.value.trim();
                if (!kw) return;
                const r = await fetch('/keywords/add', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: 'keyword=' + encodeURIComponent(kw)
                });
                if (r.ok) {
                    input.value = '';
                    document.getElementById('kw-msg').textContent = 'Added: ' + kw;
                    loadKeywords();
                } else if (r.status === 409) {
                    document.getElementById('kw-msg').style.color = '#f59e0b';
                    document.getElementById('kw-msg').textContent = 'Already exists: ' + kw;
                }
            }
            async function removeKeyword(kw) {
                if (!confirm('Remove "' + kw + '" and purge all vault files containing it?')) return;
                const r = await fetch('/keywords/remove', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: 'keyword=' + encodeURIComponent(kw)
                });
                if (r.ok) {
                    const data = await r.json();
                    document.getElementById('kw-msg').style.color = '#a3e635';
                    document.getElementById('kw-msg').textContent =
                        'Removed: ' + kw + (data.purged_count > 0 ? ' (' + data.purged_count + ' files purged)' : '');
                    loadKeywords();
                }
            }
            loadKeywords();
        </script>
```

- [ ] **Step 2: Verify app starts without errors**

Run: `timeout 5 python -c "from app import app; print('app imports OK')" 2>&1`
Expected: `app imports OK`

- [ ] **Step 3: Commit**

```bash
git add templates/index.html
git commit -m "feat: add Keywords UI panel to web interface"
```

---

## Spec Coverage Check

- [x] `vault/.interests` file storage → Task 1
- [x] `load_manual_keywords`, `save_manual_keywords` → Task 1
- [x] `add_keyword`, `remove_keyword` → Task 1
- [x] `purge_keyword` (delete files) → Task 1
- [x] GET /keywords endpoint → Task 3
- [x] POST /keywords/add endpoint → Task 3
- [x] POST /keywords/remove endpoint → Task 3
- [x] Scheduler integration (merge manual keywords) → Task 2
- [x] UI panel with chips, add input, delete button → Task 4
- [x] Confirmation on delete → Task 4 (browser `confirm()`)

## Placeholder Scan

All steps have complete code. No TBD, TODO, or placeholder implementations.

## Type Consistency

- `load_manual_keywords(path: Path) -> list[str]`
- `save_manual_keywords(keywords: list[str], path: Path) -> None`
- `add_keyword(keyword: str, path: Path) -> None` (raises `ValueError` on duplicate)
- `remove_keyword(keyword: str, path: Path) -> None` (raises `KeyError` if not found)
- `purge_keyword(keyword: str, vault_path: Path) -> list[str]` (returns deleted file paths)
- `DiscoveryScheduler._keywords` remains `list[str]`
