# personalWiki Bug Fix: Lock Embed to FastEmbed + Remove Dangling Calls

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two bugs that break discovery pipeline and vector search — (1) dangling `_update_keyword_score` calls crash the scheduler, (2) `embed()` dimension mismatch (384 vs 1024) causes LanceDB query failures.

**Architecture:** Lock `embed()` to FastEmbed BAAI/bge-small-en-v1.5 (384d) permanently — remove LM Studio path. Remove orphaned method calls. Single commit.

**Tech Stack:** FastEmbed, LanceDB, Python 3.13

---

## Root Cause Analysis

### Bug 1: Dangling `_update_keyword_score` calls
- Commit `7d89b0c` (Apr 22) removed `_update_keyword_score()` METHOD and `_keyword_scores` DICT from `DiscoveryScheduler`
- But call sites at lines 680 and 692 were left intact
- Result: every discovery cycle crashes on first ingest success/fail with `AttributeError`

### Bug 2: Vector dimension mismatch
- `embed()` tries LM Studio first (qwen3 → 1024d), silently falls back to FastEmbed (384d) on timeout
- `SCHEMA` in `vector_store.py` was 384d (committed), then `af3bd58` changed it to 1024d (matching qwen3)
- Uncommitted local edit then reverted 1024→384
- Current state: `embed()` returns 384d (LM Studio unavailable → fastembed fallback active), but SCHEMA is 384d — this "works" by accident
- Risk: if LM Studio comes up, `embed()` returns 1024d but SCHEMA expects 384d → inserts crash
- Root fix: remove LM Studio path entirely, always use fastembed

---

## Files to Modify

| File | Change |
|------|--------|
| `core/embeddings.py` | Rewrite to use fastembed only; remove LM Studio try/except path |
| `core/vector_store.py` | Explicitly set SCHEMA vector to 384d |
| `core/discovery_scheduler.py` | Delete 2 dangling call lines |
| `core/config.py` | Remove `LM_STUDIO_URL` and `LM_STUDIO_EMBED_MODEL` (dead code) |
| `Tests/test_embeddings.py` | Verify test expects 384d |

---

## Module Design Block

### Module: `core/embeddings.py`
- **Responsibility:** Generate fixed-dimension embedding vectors from text
- **Interface:** `embed(text: str) -> list[float]` — always returns 384d
- **Dependencies:** FastEmbed `TextEmbedding`, `config.EMBED_MODEL`
- **Size target:** ~15 lines — single responsibility

---

## Tasks

### Task 1: Rewrite `core/embeddings.py` — FastEmbed only

- [ ] **Step 1: Write new embeddings.py**

```python
from fastembed import TextEmbedding
from config import EMBED_MODEL

_model: "TextEmbedding | None" = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(EMBED_MODEL)
    return _model


def embed(text: str) -> list[float]:
    model = _get_model()
    vectors = list(model.embed([text]))
    return vectors[0].tolist()
```

- [ ] **Step 2: Run test to verify it works**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate
python3 -c "from core.embeddings import embed; print(len(embed('test')))"
```
Expected output: `384`

- [ ] **Step 3: Commit embeddings.py change**

```bash
git add core/embeddings.py
git commit -m "refactor: lock embed() to fastembed 384d, remove LM Studio path"
```

---

### Task 2: Set `vector_store.py` SCHEMA to 384d (intentionally)

- [ ] **Step 1: Discard any uncommitted changes, then set to 384d**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki
git checkout core/vector_store.py  # discard uncommitted 384 revert
# Now explicitly set to 384d — replace 1024 with 384
sed -i '' 's/pa.list_(pa.float32(), 1024)/pa.list_(pa.float32(), 384)/' core/vector_store.py
```

- [ ] **Step 2: Verify**

```bash
grep "pa.list_(pa.float32" core/vector_store.py
```
Expected: `pa.field("vector", pa.list_(pa.float32(), 384)),`

- [ ] **Step 3: Commit**

```bash
git add core/vector_store.py
git commit -m "fix: set SCHEMA vector to 384d to match embed() output"
```

---

### Task 3: Remove dangling `_update_keyword_score` calls from `discovery_scheduler.py`

- [ ] **Step 1: Delete line ~680**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki
sed -i '' '/self._update_keyword_score(keyword, +1)/d' core/discovery_scheduler.py
```

- [ ] **Step 2: Delete line ~692 (now shifted)**

```bash
sed -i '' '/self._update_keyword_score(keyword, -2)/d' core/discovery_scheduler.py
```

- [ ] **Step 3: Verify removals**

```bash
grep "_update_keyword_score" core/discovery_scheduler.py
```
Expected: no output

- [ ] **Step 4: Commit**

```bash
git add core/discovery_scheduler.py
git commit -m "fix: remove dangling _update_keyword_score calls from discovery cycle"
```

---

### Task 4: Remove dead LM Studio config vars from `config.py`

- [ ] **Step 1: Remove LM_STUDIO_URL and LM_STUDIO_EMBED_MODEL from config.py**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki
# Remove lines containing LM_STUDIO_URL and LM_STUDIO_EMBED_MODEL
sed -i '' '/LM_STUDIO_URL/d' core/config.py
sed -i '' '/LM_STUDIO_EMBED_MODEL/d' core/config.py
```

- [ ] **Step 2: Verify**

```bash
grep -n "LM_STUDIO" core/config.py
```
Expected: no output

- [ ] **Step 3: Commit**

```bash
git add core/config.py
git commit -m "chore: remove dead LM_STUDIO config vars"
```

---

### Task 5: Verify all tests pass

- [ ] **Step 1: Run embeddings tests**

```bash
cd /Users/vladbrincoveanu/Desktop/Startup/personalWiki && source .venv/bin/activate
pytest Tests/test_embeddings.py -v
```
Expected: all pass (cosine threshold 0.7 is verified working with fastembed at 0.779)

- [ ] **Step 2: Run discovery scheduler tests (if any exist)**

```bash
pytest Tests/ -v -k "discovery" --ignore=Tests/test_ingesters.py
```

---

## Summary of Commits

| # | Commit message |
|---|---------------|
| 1 | `refactor: lock embed() to fastembed 384d, remove LM Studio path` |
| 2 | `fix: set SCHEMA vector to 384d to match embed() output` |
| 3 | `fix: remove dangling _update_keyword_score calls from discovery cycle` |
| 4 | `chore: remove dead LM_STUDIO config vars` |

---

## Post-Fix Verification

After all tasks:
1. `embed('test')` returns exactly 384 dimensions
2. `grep "pa.list_(pa.float32" core/vector_store.py` shows `384`
3. `grep "_update_keyword_score" core/discovery_scheduler.py` returns nothing
4. `pytest Tests/test_embeddings.py -v` all pass
5. No LM Studio references remain in `core/`
