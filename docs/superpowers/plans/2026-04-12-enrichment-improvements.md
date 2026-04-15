# Enrichment Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add entities/wikilinks, figure captions, and a personal context stub to every ingested note in a single updated MiniMax LLM call.

**Architecture:** The MiniMax prompt is extended to return three new JSON fields (`entities`, `figure_captions`, `why_saved_hint`). A new `vault/entities.py` module creates stub notes for each entity. `vault/writer.py` reads the new fields and emits an Entities section, a Why I Saved This section, and inline figure captions. No changes to `pipeline.py` or the ingestion layer.

**Tech Stack:** Python, `python-frontmatter`, `requests`, `pytest`

---

## File Map

| File | Change |
|------|--------|
| `core/minimax_client.py` | Extend prompt template + fallback with 3 new fields |
| `vault/entities.py` | New — `upsert_entity_notes()` creates stub notes |
| `vault/writer.py` | Add Entities section, Why I Saved This section, figure captions |
| `tests/test_minimax_client.py` | Add tests for new fields in response + fallback |
| `tests/test_entities.py` | New — tests for entity stub creation |
| `tests/test_writer.py` | Add tests for new sections and captioned figures |

---

### Task 1: Extend enrichment prompt with `entities`, `figure_captions`, `why_saved_hint`

**Files:**
- Modify: `core/minimax_client.py`
- Test: `tests/test_minimax_client.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_minimax_client.py`:

```python
def test_enrich_returns_entities_and_figure_captions():
    import json
    from unittest.mock import patch, MagicMock
    from core.minimax_client import enrich

    mock_response = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "title": "Test Paper",
                    "type": "paper",
                    "tags": ["ml"],
                    "summary": "A test summary.",
                    "key_facts": ["Fact one"],
                    "cross_links": [],
                    "entities": [
                        {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"}
                    ],
                    "figure_captions": ["Overview of the model architecture"],
                    "why_saved_hint": "Relevant to my research on X.",
                })
            }
        }]
    }
    with patch("core.minimax_client.MINIMAX_API_KEY", "test-key"), \
         patch("core.minimax_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
        )
        result = enrich(
            raw_text="Some content <!-- image --> more content.",
            similar_titles=[],
            source="https://example.com/paper.pdf",
        )

    assert result["entities"] == [{"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"}]
    assert result["figure_captions"] == ["Overview of the model architecture"]
    assert result["why_saved_hint"] == "Relevant to my research on X."


def test_enrich_fallback_includes_new_field_defaults():
    from unittest.mock import patch
    from core.minimax_client import enrich

    with patch("core.minimax_client.requests.post") as mock_post:
        mock_post.side_effect = Exception("connection refused")
        result = enrich(
            raw_text="Some content.",
            similar_titles=[],
            source="https://example.com",
        )

    assert result["entities"] == []
    assert result["figure_captions"] == []
    assert result["why_saved_hint"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_minimax_client.py::test_enrich_returns_entities_and_figure_captions tests/test_minimax_client.py::test_enrich_fallback_includes_new_field_defaults -v
```

Expected: FAIL — `KeyError: 'entities'` or assertion error

- [ ] **Step 3: Update `core/minimax_client.py`**

Replace the full file:

```python
import json
import logging
import requests
from config import MINIMAX_API_KEY, MINIMAX_GROUP_ID, MINIMAX_MODEL, MINIMAX_API_URL

_logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a knowledge curator. Given raw text from a source, extract and structure it into a research note.
Always respond with valid JSON only — no markdown fences, no explanation."""

_NOTE_TEMPLATE = """
Analyze this content and respond with JSON in exactly this structure:
{{
  "title": "concise descriptive title",
  "type": "paper|article|video|personal",
  "tags": ["tag1", "tag2", "tag3"],
  "summary": "2-3 sentence synthesis of the main insight",
  "key_facts": ["fact 1", "fact 2", "fact 3"],
  "cross_links": ["existing-note-slug-1", "existing-note-slug-2"],
  "entities": [
    {{"name": "Display Name", "slug": "display-name", "type": "concept|person|institution|dataset|method"}}
  ],
  "figure_captions": ["one-line caption for figure 1 inferred from surrounding text", "caption for figure 2"],
  "why_saved_hint": "one sentence about why this source is worth keeping"
}}

Rules:
- entities: extract recurring concepts, people, institutions, datasets, and methods that deserve their own notes. slug must be lowercase with hyphens (e.g. "MIMIC-IV" → "mimic-iv"). Only include entities that appear meaningfully in the content.
- figure_captions: the raw content contains <!-- image --> placeholders where figures appear. Generate one caption per placeholder IN ORDER based on the surrounding text. Return an empty list if there are no <!-- image --> placeholders.
- cross_links: use slugs of existing notes listed below only if genuinely relevant.
- why_saved_hint: one sentence starter for a personal note about relevance — be specific, not generic.

Source: {source}

Existing notes in my vault that may be related (use their slugs for cross_links only if genuinely relevant):
{similar}

Raw content to analyze:
{raw_text}
"""


def _build_prompt(raw_text: str, similar_titles: list[str], source: str) -> str:
    similar_str = "\n".join(f"- {t}" for t in similar_titles) if similar_titles else "(none yet)"
    return _NOTE_TEMPLATE.format(
        source=source,
        similar=similar_str,
        raw_text=raw_text[:6000],
    )


def enrich(raw_text: str, similar_titles: list[str], source: str) -> dict:
    if not MINIMAX_API_KEY:
        _logger.warning("MINIMAX_API_KEY is not set — returning fallback for source=%s", source)
        return {
            "title": "Untitled",
            "type": "article",
            "tags": [],
            "summary": "",
            "key_facts": [],
            "cross_links": [],
            "entities": [],
            "figure_captions": [],
            "why_saved_hint": "",
            "raw_text": raw_text,
            "error": True,
        }
    prompt = _build_prompt(raw_text, similar_titles, source)
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MINIMAX_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        resp = requests.post(MINIMAX_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code") and base_resp["status_code"] != 0:
            raise ValueError(f"Minimax API error {base_resp['status_code']}: {base_resp.get('status_msg')}")
        if "choices" not in data:
            _logger.error("Minimax unexpected response for source=%s: %s", source, data)
            raise ValueError(f"No 'choices' in Minimax response: {data}")
        content = data["choices"][0]["message"]["content"]
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(content)
        data.setdefault("entities", [])
        data.setdefault("figure_captions", [])
        data.setdefault("why_saved_hint", "")
        data.setdefault("raw_text", raw_text)
        data.setdefault("error", False)
        return data
    except Exception as e:
        _logger.warning("Minimax enrich failed for source=%s: %s", source, e)
        return {
            "title": "Untitled",
            "type": "article",
            "tags": [],
            "summary": "",
            "key_facts": [],
            "cross_links": [],
            "entities": [],
            "figure_captions": [],
            "why_saved_hint": "",
            "raw_text": raw_text,
            "error": True,
        }
```

- [ ] **Step 4: Run all minimax tests**

```
pytest tests/test_minimax_client.py -v
```

Expected: All 5 tests pass

- [ ] **Step 5: Commit**

```bash
git add core/minimax_client.py tests/test_minimax_client.py
git commit -m "feat: extend enrichment prompt with entities, figure_captions, why_saved_hint"
```

---

### Task 2: Create `vault/entities.py` with `upsert_entity_notes()`

**Files:**
- Create: `vault/entities.py`
- Test: `tests/test_entities.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entities.py`:

```python
import tempfile
from pathlib import Path
from unittest.mock import patch
import frontmatter
from vault.entities import upsert_entity_notes


def test_upsert_creates_stub_notes():
    entities = [
        {"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"},
        {"name": "ROC Analysis", "slug": "roc-analysis", "type": "concept"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.entities.NOTES_DIR", notes_dir):
            upsert_entity_notes(entities)

        assert (notes_dir / "mimic-iv.md").exists()
        assert (notes_dir / "roc-analysis.md").exists()

        post = frontmatter.load(str(notes_dir / "mimic-iv.md"))
        assert post.metadata["title"] == "MIMIC-IV"
        assert post.metadata["type"] == "dataset"
        assert "_Not filled in yet._" in post.content


def test_upsert_does_not_overwrite_existing_note():
    entities = [{"name": "MIMIC-IV", "slug": "mimic-iv", "type": "dataset"}]
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        existing = notes_dir / "mimic-iv.md"
        existing.write_text("---\ntitle: MIMIC-IV\n---\nMy custom content.")

        with patch("vault.entities.NOTES_DIR", notes_dir):
            upsert_entity_notes(entities)

        assert "My custom content." in existing.read_text()


def test_upsert_skips_entities_with_missing_fields():
    entities = [
        {"name": "", "slug": "empty-name", "type": "concept"},
        {"name": "Valid Entity", "slug": "", "type": "concept"},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.entities.NOTES_DIR", notes_dir):
            upsert_entity_notes(entities)

        assert list(notes_dir.iterdir()) == []


def test_upsert_empty_list_is_noop():
    with tempfile.TemporaryDirectory() as tmp:
        notes_dir = Path(tmp) / "notes"
        notes_dir.mkdir()
        with patch("vault.entities.NOTES_DIR", notes_dir):
            upsert_entity_notes([])

        assert list(notes_dir.iterdir()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_entities.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'vault.entities'`

- [ ] **Step 3: Create `vault/entities.py`**

```python
from datetime import date
from pathlib import Path
import frontmatter
from config import NOTES_DIR


def upsert_entity_notes(entities: list[dict]) -> None:
    """Create stub notes for entities that don't yet exist. Never overwrites."""
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    for entity in entities:
        slug = entity.get("slug", "")
        name = entity.get("name", "")
        entity_type = entity.get("type", "concept")
        if not slug or not name:
            continue
        filepath = NOTES_DIR / f"{slug}.md"
        if filepath.exists():
            continue
        metadata = {
            "title": name,
            "type": entity_type,
            "tags": [],
            "created": str(date.today()),
        }
        post = frontmatter.Post("_Not filled in yet._", **metadata)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(frontmatter.dumps(post))
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_entities.py -v
```

Expected: All 4 tests pass

- [ ] **Step 5: Commit**

```bash
git add vault/entities.py tests/test_entities.py
git commit -m "feat: add upsert_entity_notes to create Obsidian entity stubs"
```

---

### Task 3: Update `vault/writer.py` with new sections and figure captions

**Files:**
- Modify: `vault/writer.py`
- Test: `tests/test_writer.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_writer.py`:

```python
def test_write_note_entities_section():
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
            {"name": "ROC Analysis", "slug": "roc-analysis", "type": "concept"},
        ],
        "figure_captions": [],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir), \
             patch("vault.writer.VAULT_PATH", tmp_path), \
             patch("vault.entities.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        assert "## Entities" in post.content
        assert "[[MIMIC-IV]]" in post.content
        assert "[[ROC Analysis]]" in post.content


def test_write_note_why_saved_section():
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some content.",
        "error": False,
        "entities": [],
        "figure_captions": [],
        "why_saved_hint": "Relevant to my robot learning work.",
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir), \
             patch("vault.writer.VAULT_PATH", tmp_path), \
             patch("vault.entities.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        assert "## Why I Saved This" in post.content
        assert "Relevant to my robot learning work." in post.content
        assert "_(edit this)_" in post.content


def test_write_note_figure_captions_injected():
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Intro <!-- image --> middle <!-- image --> end.",
        "error": False,
        "entities": [],
        "figure_captions": ["Model architecture overview", "Training reward curves"],
        "why_saved_hint": "",
    }
    import struct, zlib

    def minimal_png():
        sig = b'\x89PNG\r\n\x1a\n'
        ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data)
        ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
        raw = b'\x00\xff\x00\x00'
        compressed = zlib.compress(raw)
        idat_crc = zlib.crc32(b'IDAT' + compressed)
        idat = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc)
        iend_crc = zlib.crc32(b'IEND')
        iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
        return sig + ihdr + idat + iend

    images = [minimal_png(), minimal_png()]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir), \
             patch("vault.writer.VAULT_PATH", tmp_path), \
             patch("vault.entities.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com", images=images)

        post = frontmatter.load(path)
        assert "*Figure 1: Model architecture overview.*" in post.content
        assert "*Figure 2: Training reward curves.*" in post.content
        assert "<!-- image -->" not in post.content


def test_write_note_no_entities_section_when_empty():
    note = {
        "title": "Test Paper",
        "type": "paper",
        "tags": [],
        "summary": "A summary.",
        "key_facts": [],
        "cross_links": [],
        "raw_text": "Some content.",
        "error": False,
        "entities": [],
        "figure_captions": [],
        "why_saved_hint": "",
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        with patch("vault.writer.NOTES_DIR", notes_dir), \
             patch("vault.writer.VAULT_PATH", tmp_path), \
             patch("vault.entities.NOTES_DIR", notes_dir):
            path = write_note(note, source="https://example.com")

        post = frontmatter.load(path)
        assert "## Entities" not in post.content
        assert "## Why I Saved This" not in post.content
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_writer.py::test_write_note_entities_section tests/test_writer.py::test_write_note_why_saved_section tests/test_writer.py::test_write_note_figure_captions_injected tests/test_writer.py::test_write_note_no_entities_section_when_empty -v
```

Expected: FAIL — `AssertionError` (sections not present)

- [ ] **Step 3: Update `vault/writer.py`**

Replace the full file:

```python
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
import frontmatter
from config import NOTES_DIR, VAULT_PATH


def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug


def _save_images(images: Sequence[bytes], slug: str) -> None:
    images_dir = VAULT_PATH / "attachments" / slug
    images_dir.mkdir(parents=True, exist_ok=True)
    for i, png_bytes in enumerate(images, start=1):
        (images_dir / f"figure-{i}.png").write_bytes(png_bytes)


def _replace_image_placeholders(
    text: str, slug: str, count: int, captions: list[str] = ()
) -> str:
    result = text
    for i in range(1, count + 1):
        caption = captions[i - 1] if i - 1 < len(captions) else ""
        if caption:
            replacement = f"*Figure {i}: {caption}.*\n![[attachments/{slug}/figure-{i}.png]]"
        else:
            replacement = f"![[attachments/{slug}/figure-{i}.png]]"
        result = result.replace("<!-- image -->", replacement, 1)
    return result


def write_note(
    note: dict,
    source: str,
    ingested_date: str | None = None,
    images: Sequence[bytes] = (),
) -> str:
    from vault.entities import upsert_entity_notes

    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    title = note.get("title") or "Untitled"
    ingested_date = ingested_date or str(date.today())
    slug = slugify(title)
    filepath = NOTES_DIR / f"{slug}.md"

    # Handle slug collisions
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
        links = " · ".join(f"[[{e['name']}]]" for e in entities if e.get("name"))
        if links:
            entities_section = f"\n## Entities\n{links}\n"

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
        upsert_entity_notes(entities)

    return str(filepath)
```

- [ ] **Step 4: Run all writer tests**

```
pytest tests/test_writer.py -v
```

Expected: All 12 tests pass

- [ ] **Step 5: Run full suite**

```
pytest tests/ --ignore=tests/test_vector_store.py -v
```

Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add vault/writer.py tests/test_writer.py
git commit -m "feat: add entities section, why saved stub, and figure captions to notes"
```

---

## Self-Review

**Spec coverage:**
- `entities` JSON field + fallback default ✓ (Task 1)
- `figure_captions` JSON field + fallback default ✓ (Task 1)
- `why_saved_hint` JSON field + fallback default ✓ (Task 1)
- `upsert_entity_notes()` creates stub notes, never overwrites ✓ (Task 2)
- `## Entities` section in note ✓ (Task 3)
- `## Why I Saved This` section with hint + edit stub ✓ (Task 3)
- Figure captions injected above wikilinks ✓ (Task 3)
- No entities section when entities is empty ✓ (Task 3)
- YAML frontmatter unchanged ✓ (no frontmatter changes in any task)
- No changes to pipeline.py or ingesters/ ✓

**Placeholder scan:** No TBDs. All steps have complete code.

**Type consistency:**
- `upsert_entity_notes(entities: list[dict])` defined in Task 2, called in Task 3 ✓
- `_replace_image_placeholders(text, slug, count, captions=[])` — `captions` param added in Task 3, matches usage ✓
- `note.get("entities", [])`, `note.get("figure_captions", [])`, `note.get("why_saved_hint", "")` — all defaulted in Task 1 fallback ✓
