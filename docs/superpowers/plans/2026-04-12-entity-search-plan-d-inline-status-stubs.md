# Entity Web Search — Plan D: Inline Per-Entity Status + Auto-Updating Stubs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After enrichment, perform web searches for entities that are tools/libraries/frameworks. Annotate each entity wikilink in the `## Entities` section with inline status (version + maintenance). Also update the entity stub note's frontmatter with `version`, `status`, and `last_checked` fields so stubs stay current.

**Architecture:** A new `vault/entity_status.py` module performs web searches for tool/library entities. `vault/writer.py` renders entities with inline status annotations (`[[PyTorch]] v2.5.1 · actively maintained`). `vault/entities.py` is extended to update existing stub frontmatter with status metadata. Entity type filter: `type == "library" or type == "framework" or type == "tool"`.

**Tech Stack:** Python, `requests` (for GitHub/PyPI APIs), `python-frontmatter`, `pytest`

---

## File Map

| File | Change |
|------|--------|
| `vault/entity_status.py` | New — `fetch_entity_status(entities) -> list[dict]` performs web searches |
| `vault/entities.py` | Extend `upsert_entity_notes()` to update frontmatter with status metadata |
| `vault/writer.py` | Render entity wikilinks with inline status annotations |
| `pipeline.py` | Thread `entity_statuses` through pipeline after enrichment |
| `tests/test_entity_status.py` | New — tests for search, filtering, and inline annotation |
| `tests/test_entities.py` | Add tests for entity stub frontmatter updates |
| `tests/test_writer.py` | Add test for inline entity status annotations |

---

### Task 1: Create `vault/entity_status.py` with search and filtering

**Files:**
- Create: `vault/entity_status.py`
- Test: `tests/test_entity_status.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entity_status.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from vault.entity_status import fetch_entity_status, _is_library_entity


def test_is_library_entity_filters_correctly():
    assert _is_library_entity({"name": "PyTorch", "slug": "pytorch", "type": "library"}) is True
    assert _is_library_entity({"name": "React", "slug": "react", "type": "framework"}) is True
    assert _is_library_entity({"name": "crawl4ai", "slug": "crawl4ai", "type": "tool"}) is True
    assert _is_library_entity({"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"}) is False
    assert _is_library_entity({"name": "Attention Mechanism", "slug": "attention-mechanism", "type": "concept"}) is False
    assert _is_library_entity({"name": "Yann LeCun", "slug": "yann-lecun", "type": "person"}) is False


def test_fetch_entity_status_returns_structured_results():
    entities = [
        {"name": "PyTorch", "slug": "pytorch", "type": "library"},
        {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
    ]
    mock_results = {
        "PyTorch": {"version": "v2.5.1", "status": "actively maintained", "source": "PyPI"},
        "MIMIC-IV": None,
    }

    def mock_search(name, slug):
        return mock_results.get(name)

    with patch("vault.entity_status._search_library_status", mock_search):
        result = fetch_entity_status(entities)

    assert len(result) == 1
    assert result[0]["name"] == "PyTorch"
    assert result[0]["version"] == "v2.5.1"
    assert result[0]["status"] == "actively maintained"


def test_fetch_entity_status_empty_when_no_library_entities():
    entities = [
        {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
        {"name": "Attention Mechanism", "slug": "attention-mechanism", "type": "concept"},
    ]
    result = fetch_entity_status(entities)
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_entity_status.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'vault.entity_status'`

- [ ] **Step 3: Create `vault/entity_status.py`**

```python
import logging
import requests
from datetime import date
from typing import Optional

_logger = logging.getLogger(__name__)

_LIBRARY_TYPES = {"library", "framework", "tool"}


def _is_library_entity(entity: dict) -> bool:
    """Return True if entity type is tool/library/framework."""
    if not isinstance(entity, dict):
        return False
    return entity.get("type", "").lower() in _LIBRARY_TYPES


def _search_library_status(name: str, slug: str) -> Optional[dict]:
    """
    Perform web search for library/tool/framework version and status.
    Uses GitHub API for GitHub-hosted projects, PyPI API otherwise.
    Returns None if nothing found.
    """
    github_api = f"https://api.github.com/repos/{slug.replace('-', '_')}"
    try:
        resp = requests.get(github_api, timeout=5, headers={"Accept": "application/vnd.github.v3+json"})
        if resp.status_code == 200:
            data = resp.json()
            return {
                "version": data.get("tag_name", data.get("name", "")),
                "status": "actively maintained" if data.get("pushed_at") else "archived",
                "source": f"GitHub ({data.get('full_name', '')})",
            }
    except Exception as e:
        _logger.debug("GitHub search failed for %s: %s", slug, e)

    pypi_url = f"https://pypi.org/pypi/{slug}/json"
    try:
        resp = requests.get(pypi_url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            info = data.get("info", {})
            return {
                "version": info.get("version", ""),
                "status": "actively maintained" if not info.get("yanked") else "yanked",
                "source": "PyPI",
            }
    except Exception as e:
        _logger.debug("PyPI search failed for %s: %s", slug, e)

    return None


def fetch_entity_status(entities: list[dict]) -> list[dict]:
    """
    Filter entities to only tool/library/framework types and fetch their web status.
    Returns list of dicts: {name, slug, version, status, source}
    """
    results = []
    for entity in entities:
        if not _is_library_entity(entity):
            continue
        name = entity.get("name", "")
        slug = entity.get("slug", "")
        if not name or not slug:
            continue
        status = _search_library_status(name, slug)
        if status:
            results.append({
                "name": name,
                "slug": slug,
                **status,
                "last_checked": str(date.today()),
            })
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_entity_status.py -v
```

Expected: All 3 tests pass

- [ ] **Step 5: Commit**

```bash
git add vault/entity_status.py tests/test_entity_status.py
git commit -m "feat: add entity_status module for library/tool web search"
```

---

### Task 2: Extend `vault/entities.py` to update stub frontmatter with status

**Files:**
- Modify: `vault/entities.py`
- Test: `tests/test_entities.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_entities.py`:

```python
def test_upsert_updates_existing_stub_with_status():
    """When entity stub exists, update frontmatter with status metadata."""
    import tempfile
    from pathlib import Path
    from vault.entities import upsert_entity_notes
    import frontmatter

    entities = [
        {"name": "PyTorch", "slug": "pytorch", "type": "library"},
    ]
    statuses = [
        {"name": "PyTorch", "slug": "pytorch", "version": "v2.5.1", "status": "actively maintained", "source": "PyPI", "last_checked": "2026-04-12"},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        existing = notes_dir / "pytorch.md"
        existing.write_text("---\ntitle: PyTorch\ntype: library\n---\n_Not filled in yet._")

        with patch("vault.entities.NOTES_DIR", notes_dir):
            upsert_entity_notes(entities, statuses)

        post = frontmatter.load(str(existing))
        assert post.metadata["version"] == "v2.5.1"
        assert post.metadata["status"] == "actively maintained"
        assert post.metadata["last_checked"] == "2026-04-12"
        assert "_Not filled in yet._" in post.content


def test_upsert_creates_new_stub_with_status():
    """When entity stub doesn't exist, create it with status metadata."""
    import tempfile
    from pathlib import Path
    from vault.entities import upsert_entity_notes
    import frontmatter

    entities = [
        {"name": "crawl4ai", "slug": "crawl4ai", "type": "tool"},
    ]
    statuses = [
        {"name": "crawl4ai", "slug": "crawl4ai", "version": "v0.3.0", "status": "actively maintained", "source": "GitHub", "last_checked": "2026-04-12"},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()

        with patch("vault.entities.NOTES_DIR", notes_dir):
            upsert_entity_notes(entities, statuses)

        post = frontmatter.load(str(notes_dir / "crawl4ai.md"))
        assert post.metadata["version"] == "v0.3.0"
        assert post.metadata["status"] == "actively maintained"
        assert post.metadata["last_checked"] == "2026-04-12"
```

- [ ] **Step 2: Run new tests to verify they fail**

```
pytest tests/test_entities.py::test_upsert_updates_existing_stub_with_status tests/test_entities.py::test_upsert_creates_new_stub_with_status -v
```

Expected: FAIL — `upsert_entity_notes() takes 1 positional argument but 2 were given`

- [ ] **Step 3: Update `vault/entities.py`**

Replace the file:

```python
from datetime import date
from pathlib import Path
import frontmatter
from config import NOTES_DIR


def upsert_entity_notes(entities: list[dict], statuses: list[dict] = ()) -> None:
    """
    Create stub notes for entities that don't yet exist. Never overwrites content.

    For entities that already have stubs, update frontmatter with status metadata
    (version, status, source, last_checked) if status info is provided.
    """
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    status_map = {s["slug"]: s for s in statuses}

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        slug = entity.get("slug", "")
        name = entity.get("name", "")
        entity_type = entity.get("type", "concept")
        if not slug or not name:
            continue
        filepath = NOTES_DIR / f"{slug}.md"
        if not filepath.resolve().is_relative_to(NOTES_DIR.resolve()):
            continue

        entity_status = status_map.get(slug, {})

        if filepath.exists():
            post = frontmatter.load(str(filepath))
            if entity_status:
                post.metadata["version"] = entity_status.get("version", "")
                post.metadata["status"] = entity_status.get("status", "")
                post.metadata["source"] = entity_status.get("source", "")
                post.metadata["last_checked"] = entity_status.get("last_checked", str(date.today()))
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(frontmatter.dumps(post))
        else:
            metadata = {
                "title": name,
                "type": entity_type,
                "tags": [],
                "created": str(date.today()),
            }
            if entity_status:
                metadata["version"] = entity_status.get("version", "")
                metadata["status"] = entity_status.get("status", "")
                metadata["source"] = entity_status.get("source", "")
                metadata["last_checked"] = entity_status.get("last_checked", str(date.today()))
            post = frontmatter.Post("_Not filled in yet._", **metadata)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(frontmatter.dumps(post))
```

- [ ] **Step 4: Run entity tests to verify they pass**

```
pytest tests/test_entities.py -v
```

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add vault/entities.py tests/test_entities.py
git commit -m "feat: extend upsert_entity_notes to update stub frontmatter with status"
```

---

### Task 3: Update `vault/writer.py` with inline entity status annotations

**Files:**
- Modify: `vault/writer.py`
- Test: `tests/test_writer.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_writer.py`:

```python
def test_write_note_entities_with_inline_status():
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some content.",
        "error": False,
        "entities": [
            {"name": "PyTorch", "slug": "pytorch", "type": "library"},
            {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
        ],
        "figure_captions": [],
        "why_saved_hint": "",
    }
    entity_statuses = [
        {"name": "PyTorch", "slug": "pytorch", "version": "v2.5.1", "status": "actively maintained", "source": "PyPI"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir), \
             patch("vault.writer.VAULT_PATH", tmp_path):
            path = write_note(note, source="https://example.com", entity_statuses=entity_statuses)

        post = frontmatter.load(path)
        assert "## Entities" in post.content
        assert "[[PyTorch]] v2.5.1 · actively maintained" in post.content
        assert "[[MIMIC-IV]]" in post.content


def test_write_note_entities_without_status():
    """Non-library entities render without status annotation."""
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some content.",
        "error": False,
        "entities": [
            {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
        ],
        "figure_captions": [],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir), \
             patch("vault.writer.VAULT_PATH", tmp_path):
            path = write_note(note, source="https://example.com", entity_statuses=[])

        post = frontmatter.load(path)
        assert "## Entities" in post.content
        assert "[[MIMIC-IV]]" in post.content
        assert "v2.5.1" not in post.content
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_writer.py::test_write_note_entities_with_inline_status tests/test_writer.py::test_write_note_entities_without_status -v
```

Expected: FAIL — `write_note() got an unexpected keyword argument 'entity_statuses'`

- [ ] **Step 3: Update `vault/writer.py`**

Replace `write_note()` signature and body:

```python
def write_note(
    note: dict,
    source: str,
    ingested_date: str | None = None,
    images: Sequence[bytes] = (),
    entity_statuses: list[dict] = (),
) -> str:
    from vault.entities import upsert_entity_notes

    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    title = note.get("title") or "Untitled"
    ingested_date = ingested_date or str(date.today())
    slug = slugify(title)
    filepath = NOTES_DIR / f"{slug}.md"

    counter = 1
    while filepath.exists():
        filepath = NOTES_DIR / f"{slug}-{counter}.md"
        counter += 1
    final_slug = filepath.stem

    metadata = {
        "title": title,
        "source": source,
        "type": note.get("type", "article"),
        "tags": note.get("tags", []),
        "ingested": ingested_date,
    }
    if note.get("error"):
        metadata["confidence"] = "low"

    cross_links = note.get("cross_links", [])
    cross_links_section = ""
    if cross_links:
        links_str = ", ".join(f"[[{l}]]" for l in cross_links)
        cross_links_section = f"\n## My Knowledge Says\n{links_str}\n"

    key_facts = note.get("key_facts", [])
    facts_str = "\n".join(f"- {f}" for f in key_facts) if key_facts else "_None extracted._"

    entities = note.get("entities", [])
    entities_section = ""
    if entities:
        status_map = {s["slug"]: s for s in entity_statuses}
        links = []
        for e in entities:
            if not e.get("name") or not e.get("slug"):
                continue
            name = e["name"]
            slug = e["slug"]
            if slug in status_map:
                s = status_map[slug]
                version_str = f"v{s.get('version', '')}" if s.get("version") else ""
                status_str = s.get("status", "")
                annotation = " · ".join(filter(None, [version_str, status_str]))
                links.append(f"[[{name}]] {annotation}" if annotation else f"[[{name}]]")
            else:
                links.append(f"[[{name}]]")
        if links:
            entities_section = f"\n## Entities\n{' · '.join(links)}\n"

    why_saved_hint = note.get("why_saved_hint", "")
    why_saved_section = ""
    if why_saved_hint:
        why_saved_section = f"\n## Why I Saved This\n> {why_saved_hint}\n\n_(edit this)_\n"

    figure_captions = note.get("figure_captions", [])
    raw_text = note.get("raw_text", "")
    if images:
        _save_images(images, final_slug)
        raw_text = _replace_image_placeholders(raw_text, final_slug, len(images), figure_captions)

    raw_section = (
        f"\n## Raw Extract\n<details>\n<summary>Original extracted text</summary>"
        f"\n\n{raw_text}\n\n</details>"
    )

    body = (
        f"## Summary\n{note.get('summary', '_Not available._')}\n\n"
        f"## Key Facts\n{facts_str}"
        f"{entities_section}{why_saved_section}{cross_links_section}{raw_section}"
    )

    post = frontmatter.Post(body, **metadata)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))

    if entities:
        upsert_entity_notes(entities, entity_statuses)

    return str(filepath)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_writer.py::test_write_note_entities_with_inline_status tests/test_writer.py::test_write_note_entities_without_status -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add vault/writer.py tests/test_writer.py
git commit -m "feat: add inline entity status annotations to ## Entities section"
```

---

### Task 4: Update `pipeline.py` to thread entity status through

**Files:**
- Modify: `pipeline.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline.py`:

```python
def test_pipeline_runs_entity_status_search_and_updates_stubs():
    with tempfile.TemporaryDirectory() as tmp:
        vault_path = Path(tmp) / "vault"
        notes_dir = vault_path / "notes"
        index_path = Path(tmp) / "index"
        notes_dir.mkdir(parents=True)
        index_path.mkdir(parents=True)

        with patch("config.VAULT_PATH", vault_path), \
             patch("config.NOTES_DIR", notes_dir), \
             patch("config.INDEX_PATH", index_path), \
             patch("core.minimax_client.MINIMAX_API_KEY", "test-key"), \
             patch("core.embeddings.embed") as mock_embed, \
             patch("core.vector_store.get_store") as mock_store, \
             patch("vault.entity_status.fetch_entity_status") as mock_status:

            mock_embed.return_value = [0.1] * 384
            store_instance = MagicMock()
            store_instance.exists.return_value = False
            store_instance.search.return_value = []
            mock_store.return_value = store_instance

            mock_status.return_value = [
                {"name": "PyTorch", "slug": "pytorch", "version": "v2.5.1", "status": "actively maintained", "source": "PyPI", "last_checked": "2026-04-12"},
            ]

            async def mock_enrich(*args, **kwargs):
                return {
                    "title": "Test Paper",
                    "type": "paper",
                    "tags": [],
                    "summary": "A summary.",
                    "key_facts": [],
                    "cross_links": [],
                    "entities": [{"name": "PyTorch", "slug": "pytorch", "type": "library"}],
                    "figure_captions": [],
                    "why_saved_hint": "",
                    "raw_text": "Some content.",
                    "error": False,
                }

            with patch("core.minimax_client.enrich", mock_enrich):
                results = []
                async for msg in run_pipeline(url="https://example.com/test"):
                    results.append(msg)

            mock_status.assert_called_once()
            assert any("Saved" in r for r in results)
            assert (notes_dir / "pytorch.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_pipeline.py::test_pipeline_runs_entity_status_search_and_updates_stubs -v
```

Expected: FAIL — `fetch_entity_status` not called

- [ ] **Step 3: Update `pipeline.py`**

Replace the file:

```python
import asyncio
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import AsyncGenerator
from config import TOP_K_SIMILAR, MAX_EMBED_CHARS
from core.embeddings import embed
from core.vector_store import get_store
from core.minimax_client import enrich
from ingesters.web import extract_url
from ingesters.pdf import extract_pdf_full
from vault.writer import write_note
from vault.entity_status import fetch_entity_status


def _is_pdf_url(url: str) -> bool:
    """Return True if the URL serves a PDF (by extension or Content-Type)."""
    if url.lower().split("?")[0].endswith(".pdf"):
        return True
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as resp:
            ct = resp.headers.get("Content-Type", "")
            return "application/pdf" in ct
    except Exception:
        return False


async def run_pipeline(
    url: str | None = None,
    pdf_path: str | None = None,
) -> AsyncGenerator[str, None]:
    store = get_store()
    source = url or pdf_path

    if url and store.exists(url):
        yield "Warning: Note for this URL already exists. Skipping."
        return

    yield "Extracting content..."
    tmp_pdf_path = None
    images: list[bytes] = []
    try:
        if url and _is_pdf_url(url):
            yield "Detected PDF URL — downloading..."
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_pdf_path = tmp.name
            await asyncio.to_thread(urllib.request.urlretrieve, url, tmp_pdf_path)
            result = await asyncio.to_thread(extract_pdf_full, tmp_pdf_path)
            raw_text = result.markdown
            images = result.images
        elif url:
            raw_text = await extract_url(url)
        else:
            result = await asyncio.to_thread(extract_pdf_full, pdf_path)
            raw_text = result.markdown
            images = result.images
    except Exception as e:
        yield f"Error during extraction: {e}"
        return
    finally:
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            os.unlink(tmp_pdf_path)

    yield "Finding similar notes..."
    vector = embed(raw_text[:MAX_EMBED_CHARS])
    similar = store.search(vector, top_k=TOP_K_SIMILAR)
    similar_titles = [
        s["metadata"].get("title", Path(s["path"]).stem)
        for s in similar
        if isinstance(s.get("metadata"), dict)
    ]
    yield f"Finding similar notes ({len(similar)} found)..."

    yield "Enriching with Minimax..."
    note = await asyncio.to_thread(enrich, raw_text, similar_titles, source)

    yield "Checking entity status..."
    entity_statuses = await asyncio.to_thread(fetch_entity_status, note.get("entities", []))

    yield "Saving note..."
    path = write_note(note, source=source, images=images, entity_statuses=entity_statuses)

    yield "Indexing..."
    index_meta = {k: v for k, v in note.items() if k != "raw_text"}
    index_meta["_file_path"] = path
    store.upsert(
        path=source,
        text=raw_text,
        vector=vector,
        links=note.get("cross_links", []),
        metadata=index_meta,
    )

    stem = Path(path).name
    yield f"Saved -> notes/{stem}"
```

- [ ] **Step 4: Run all pipeline tests**

```
pytest tests/test_pipeline.py -v
```

Expected: All pass

- [ ] **Step 5: Run full test suite**

```
pytest tests/ --ignore=tests/test_vector_store.py -v
```

Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "feat: thread entity status web search through pipeline"
```

---

## Self-Review

**Spec coverage:**
- Entity filter: tools/libraries/frameworks only ✓
- Web search for each library entity ✓
- Inline status annotation in ## Entities section (`[[PyTorch]] v2.5.1 · actively maintained`) ✓
- Entity stub frontmatter updated with version/status/source/last_checked ✓
- Non-library entities render without status annotation ✓
- No changes to enrichment layer ✓

**Placeholder scan:** No TBDs. All steps have complete code.

**Type consistency:**
- `fetch_entity_status(entities: list[dict]) -> list[dict]` ✓
- `upsert_entity_notes(entities: list[dict], statuses: list[dict] = ())` ✓
- `write_note(..., entity_statuses: list[dict] = ())` ✓
- Pipeline threads `entity_statuses` after enrich, before write ✓