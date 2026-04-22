# Keywords SOT Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify keywords to a single user-managed list. Discovery reads keywords as read-only. Deleting a keyword cascades to delete all discovery-found articles with matching `source_keyword` frontmatter.

**Architecture:** Remove amplification/graph machinery. Keywords come only from user input via UI. `remove_keyword()` now cascades by `source_keyword` frontmatter.

**Tech Stack:** Python, FastAPI, frontmatter, LanceDB

---

## File Structure After Cleanup

```
vault/
├── keywords_manager.py   # SIMPLIFIED: add/remove/list only, no suppress
core/
├── discovery_scheduler.py  # MODIFIED: amplification disabled, graph_interests deleted
├── graph_interests.py   # DELETED
app.py                  # MODIFIED: cascade delete wired to remove_keyword
templates/index.html     # MODIFIED: single keyword list UI
```

---

## Task 1: Simplify `keywords_manager.py` — remove suppress, add cascade delete

**Files:**
- Modify: `core/keywords_manager.py` (full rewrite of functions)
- Test: `tests/test_keywords_manager.py` (new file)

- [ ] **Step 1: Write failing test for cascade delete**

Create `tests/test_keywords_manager.py`:

```python
import tempfile
from pathlib import Path
from core.keywords_manager import remove_keyword, add_keyword, load_manual_keywords, save_manual_keywords

def test_remove_keyword_cascades_source_keyword():
    """Removing a keyword deletes notes where source_keyword matches."""
    from core.keywords_manager import _cascade_delete_by_source_keyword

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        vault.mkdir()
        keywords_file = Path(tmp) / "_keywords"
        keywords_file.touch()

        # Create note with source_keyword frontmatter
        note1 = vault / "article-about-ml.md"
        note1.write_text("---\nsource_keyword: machine-learning\n---\n# ML Article\nContent here.")

        # Create note without matching source_keyword
        note2 = vault / "article-about-physics.md"
        note2.write_text("---\nsource_keyword: quantum-physics\n---\n# Physics Article\nContent here.")

        result = _cascade_delete_by_source_keyword("machine-learning", vault)

        assert not note1.exists(), "source_keyword note should be deleted"
        assert note2.exists(), "non-matching note should be kept"
        assert str(note1) in result

def test_suppress_keyword_removed():
    """suppress_keyword should no longer exist."""
    from core import keywords_manager
    assert not hasattr(keywords_manager, 'suppress_keyword'), "suppress_keyword should be removed"

def test_load_suppressed_keywords_removed():
    """load_suppressed_keywords should no longer exist."""
    from core import keywords_manager
    assert not hasattr(keywords_manager, 'load_suppressed_keywords'), "load_suppressed_keywords should be removed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_keywords_manager.py -v`
Expected: FAIL with "_cascade_delete_by_source_keyword not defined"

- [ ] **Step 3: Implement cascade delete in `keywords_manager.py`**

Add at the end of the file (before any existing tests):

```python
def _cascade_delete_by_source_keyword(keyword: str, vault_path: Path) -> list[str]:
    """Delete all notes where source_keyword frontmatter equals keyword.
    Returns list of deleted file paths."""
    import frontmatter as fm
    from core.vector_store import get_store

    deleted = []
    try:
        store = get_store()
    except Exception:
        store = None

    for md_file in vault_path.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            parsed = fm.parse(content)
            if parsed is None:
                continue
            metadata, _ = parsed
            if metadata.get("source_keyword") == keyword:
                md_file.unlink()
                if store:
                    try:
                        store.delete(str(md_file))
                    except Exception:
                        pass
                deleted.append(str(md_file))
        except Exception:
            continue

    return deleted
```

- [ ] **Step 4: Update `remove_keyword()` to call cascade**

Change the `remove_keyword()` signature and body to:

```python
def remove_keyword(keyword: str, path: Path, vault_path: Path | None = None) -> list[str]:
    """Remove keyword from _keywords file and cascade delete source_keyword matches.

    Args:
        keyword: keyword to remove
        path: path to _keywords file
        vault_path: path to vault for cascade delete (optional for backwards compat)

    Returns list of deleted file paths from cascade.
    Raises KeyError if keyword not found.
    """
    existing = load_manual_keywords(path)
    if keyword not in existing:
        raise KeyError(f"Keyword '{keyword}' not found in {path}")
    existing.remove(keyword)
    save_manual_keywords(existing, path)

    cascade_deleted = []
    if vault_path and vault_path.exists():
        cascade_deleted = _cascade_delete_by_source_keyword(keyword, vault_path)

    return cascade_deleted
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_keywords_manager.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/keywords_manager.py tests/test_keywords_manager.py
git commit -m "refactor(keywords): remove suppress, add cascade delete by source_keyword"
```

---

## Task 2: Delete `core/graph_interests.py`

**Files:**
- Delete: `core/graph_interests.py`

- [ ] **Step 1: Verify no other files import graph_interests**

Run: `grep -r "from core.graph_interests\|import graph_interests" --include="*.py" .`
Expected: only the discovery_scheduler.py import (which will be removed in Task 3)

- [ ] **Step 2: Commit deletion**

```bash
git rm core/graph_interests.py
git commit -m "refactor: delete graph_interests.py — amplification era over"
```

---

## Task 3: Disable amplification in `discovery_scheduler.py`

**Files:**
- Modify: `core/discovery_scheduler.py`

- [ ] **Step 1: Write failing tests**

In `tests/test_amplification.py`, update the existing test (should already be updated from prior work):

```python
def test_amplify_from_note_does_nothing():
    """_amplify_from_note must be a no-op."""
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    original_len = len(scheduler._keywords)
    asyncio.run(scheduler._amplify_from_note({
        "title": "Test",
        "raw_text": "machine learning transformers"
    }))
    assert len(scheduler._keywords) == original_len

def test_get_explore_keywords_returns_empty():
    """_get_explore_keywords must return empty list."""
    from core.discovery_scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    assert scheduler._get_explore_keywords() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_amplification.py -v`
Expected: FAIL if amplification is still active

- [ ] **Step 3: Stub out amplification methods**

Find and replace in `discovery_scheduler.py`:

Replace `async def _amplify_from_note` (around line 249):
```python
async def _amplify_from_note(self, note: dict):
    """Amplification disabled — keywords are user-owned only."""
    return  # no-op
```

Replace `def _get_explore_keywords` (around line 262):
```python
def _get_explore_keywords(self) -> list[str]:
    """Exploration disabled — keywords are user-owned only."""
    return []
```

Remove from `_scheduler_loop` (around line 752) the block:
```python
# REMOVE these lines:
# explore_kws = self._get_explore_keywords()
# for kw in explore_kws:
#     if kw not in self._keywords:
#         self._keywords.append(kw)
#         _logger.info("Amplification: explore keyword added %r", kw)
```

Remove the import of `suppress_keyword as _km_suppress` (line 29).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_amplification.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/discovery_scheduler.py
git commit -m "refactor(discovery): disable amplification — keywords are user-owned only"
```

---

## Task 4: Wire cascade delete into `DiscoveryScheduler.remove_keyword()`

**Files:**
- Modify: `core/discovery_scheduler.py`

- [ ] **Step 1: Find `DiscoveryScheduler.remove_keyword()` method**

```bash
grep -n "def remove_keyword" core/discovery_scheduler.py
```

- [ ] **Step 2: Update the method to call cascade**

Read the current `remove_keyword` method (around line 231):

```python
def remove_keyword(self, keyword: str) -> list[str]:
    """Remove keyword from _keywords; purge from vault via purge_keyword."""
    _km_remove(keyword, KEYWORDS_FILE)
    if keyword in self._keywords:
        self._keywords.remove(keyword)
    deleted = _km_purge(keyword, Path(VAULT_PATH))
    ...
```

Replace with:

```python
def remove_keyword(self, keyword: str) -> list[str]:
    """Remove keyword from _keywords; cascade delete source_keyword notes + wikilinks."""
    _km_remove(keyword, KEYWORDS_FILE)
    if keyword in self._keywords:
        self._keywords.remove(keyword)
    # Cascade delete by source_keyword frontmatter first
    cascade_deleted = _cascade_delete_by_source_keyword(keyword, Path(VAULT_PATH))
    # Then remove wikilinks from remaining files
    wikilink_deleted = _km_purge(keyword, Path(VAULT_PATH))
    return cascade_deleted + wikilink_deleted
```

Add import at top of `discovery_scheduler.py` if not present:
```python
from core.keywords_manager import (
    load_manual_keywords as _load_manual_keywords,
    add_keyword as _km_add,
    remove_keyword as _km_remove,
    purge_keyword as _km_purge,
    _cascade_delete_by_source_keyword,
    load_suppressed_keywords as _load_suppressed,  # Keep for now - remove in Task 3
)
```

Wait — `_cascade_delete_by_source_keyword` is not in `keywords_manager.py` yet when Task 3 runs. Do Task 1 before Task 4. Order is: Task 1 → Task 4.

Actually re-read the dependency order: Task 1 first, then Task 4.

- [ ] **Step 3: Commit**

```bash
git add core/discovery_scheduler.py
git commit -m "feat(discovery): wire cascade delete into remove_keyword"
```

---

## Task 5: Update `/keywords/remove` endpoint in `app.py`

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Find and read the `/keywords/remove` endpoint**

```bash
grep -n "keywords.*remove\|remove.*keyword\|/keywords/" app.py | head -20
```

- [ ] **Step 2: Verify it calls scheduler.remove_keyword()**

The endpoint should call `scheduler.remove_keyword(kw)`. Since we updated that method in Task 4, the cascade is already wired. Likely no code change needed — just verify.

- [ ] **Step 3: Commit (if changed)**

---

## Task 6: Simplify UI — single keyword list

**Files:**
- Modify: `templates/index.html`

- [ ] **Step 1: Replace `loadKeywords()` function**

Find `async function loadKeywords()` in the template (around line 732) and replace the entire function:

```javascript
async function loadKeywords() {
    try {
        const res = await fetch('/keywords');
        const data = await res.json();
        const chips = document.getElementById('keywords-chips');
        chips.innerHTML = '';
        const kws = data.keywords || [];
        if (kws.length === 0) {
            chips.innerHTML = '<div class="kw-empty">No keywords yet</div>';
            return;
        }
        kws.forEach(kw => chips.appendChild(makeChip(kw)));
    } catch(e) { console.error('Failed to load keywords', e); }
}

function makeChip(kw) {
    const span = document.createElement('span');
    span.className = 'kw-chip';
    const txt = document.createTextNode(kw);
    span.appendChild(txt);
    const btn = document.createElement('button');
    btn.className = 'kw-remove';
    btn.textContent = '\u00d7';
    btn.onclick = (e) => { e.stopPropagation(); removeKeyword(kw); };
    span.appendChild(btn);
    return span;
}

async function removeKeyword(kw) {
    if (!confirm('Remove keyword "' + kw + '"?\n\nThis will delete all discovery articles tagged with this keyword.')) return;
    try {
        const res = await fetch('/keywords/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword: kw })
        });
        if (res.ok) loadKeywords();
    } catch(e) { console.error('Failed to remove keyword', e); }
}
```

Note: `chips.innerHTML = ''` is safe here because kws come from `/keywords` API (trusted server data).

- [ ] **Step 2: Remove the old `makeChip(kw, isManual)` function**

The old `makeChip(kw, isManual)` (line 748) should be replaced by the new `makeChip(kw)` above.

- [ ] **Step 3: Remove `addKeyword()` function**

The old `addKeyword()` and its button in the UI can be removed if the spec says no add button. Check if `addKeyword` exists and remove it if user should only manage via direct file edit.

Actually spec says "No add button in UI (user types new keywords)" — so remove `addKeyword()` function and any "+ Add" button.

- [ ] **Step 4: Commit**

```bash
git add templates/index.html
git commit -m "refactor(ui): simplify keyword UI to single list"
```

---

## Task 7: Clean up `_keywords` file (migration — manual, not code)

**Files:**
- Modify: `~/Documents/ObsidianVault/_keywords` (migration)

- [ ] **Step 1: Run cleanup script**

```bash
python3 -c "
from pathlib import Path
kw_file = Path.home() / 'Documents/ObsidianVault/_keywords'
if kw_file.exists():
    lines = [l.strip() for l in kw_file.read_text().splitlines() if l.strip()]
    # Remove URLs
    lines = [l for l in lines if not l.startswith('http://') and not l.startswith('https://')]
    # Dedupe preserving order
    seen = set(); unique = []
    for l in lines:
        if l not in seen: seen.add(l); unique.append(l)
    kw_file.write_text('\n'.join(unique) + '\n')
    print(f'Cleaned: {len(lines) - len(unique)} duplicates/URLs removed, {len(unique)} keywords remain')
"
```

- [ ] **Step 2: Delete `_keywords-suppressed`**

```bash
rm -f ~/Documents/ObsidianVault/_keywords-suppressed
echo "Deleted _keywords-suppressed"
```

- [ ] **Step 3: Delete `_graph_keywords` cache**

```bash
rm -f ~/.personalWiki/_graph_keywords
echo "Deleted _graph_keywords cache"
```

---

## Task 8: Final commit of all code changes

```bash
git add -A
git status
# Should show only modified files, no new files (graph_interests.py already deleted in Task 2)
git commit -m "cleanup: keywords SOT complete — single list, cascade delete, no amplification"
```

---

## Dependency Order

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6
                                          ↓
                                      Task 7 (manual vault files)
```

Tasks 1 and 2 can be swapped. Tasks 5 and 6 can be done in parallel with Task 4.
