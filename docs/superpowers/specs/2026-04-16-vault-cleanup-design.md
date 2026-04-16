# Vault Cleanup + Hallucination Remover Design

**Date:** 2026-04-16
**Status:** Approved

---

## Overview

Two independent cleanup systems for personalWiki:

1. **Vault junk cleanup** — removes video notes with no transcript content, runs every discovery cycle
2. **Hallucination remover** — finds dead code, unused branches, and gig tests added for quantity not quality

---

## Part 1: Vault Junk Cleanup

### Problem

YouTube videos sometimes fail to extract a transcript entirely — the pipeline creates a skeleton note with frontmatter but no body content. These notes bloat the vault and vector store with useless entries. They need to be automatically detected and deleted.

### Detection Criteria

A note is "junk" if:
- `type: video` in frontmatter **AND** (`raw_text` is absent **OR** length < 50 characters)
- **OR** title contains `[NO_TRANSCRIPT]` or `[TRANSLATION_FAILED]`

### Module: `vault/junk_cleaner.py`

```python
def cleanup_junk() -> list[str]:
    """
    Scan NOTES_DIR for junk video notes and delete them.
    Returns list of deleted file paths.
    """
```

- **Responsibility:** Detect and delete junk notes from vault + vector store
- **Interface:** `cleanup_junk() -> list[str]` (deleted paths)
- **Dependencies:** `NOTES_DIR`, `VectorStore.get_all_paths()`, `frontmatter`
- **Size target:** < 80 lines

### DiscoveryScheduler Integration

At the end of `_run_discovery_cycle()`, after all ingestion is complete:

```python
# In _run_discovery_cycle(), after the for-loop:
try:
    deleted = cleanup_junk()
    if deleted:
        _logger.info("Junk cleanup: removed %d notes", len(deleted))
except Exception as e:
    _logger.warning("Junk cleanup failed: %s", e)
```

No new dependencies added to DiscoveryScheduler — it already imports from `vault.writer`.

---

## Part 2: Hallucination Remover

### Problem

AI-generated code often includes:
- Branches that can never be reached (condition always True/False)
- Fire-and-forget calls where return values are silently dropped
- Tests that mock everything and only assert mocks were called (no real behavior tested)
- Commented-out code left behind
- `print()` / `breakpoint()` in production code

These need to be found and removed without breaking anything.

### Module: `scripts/hallucination_remover.py`

```python
def scan(path: Path, fix: bool = False) -> dict:
    """
    Scan directory for hallucination patterns.
    If fix=True, auto-remove safe patterns.
    Returns {file: [issues]}.
    """
```

- **Responsibility:** Static analysis to find dead/meaningless code
- **Interface:** CLI — `python scripts/hallucination_remover.py [--path <dir>] [--fix]`
- **Dependencies:** ast, re (stdlib only)
- **Size target:** < 200 lines

### Detection Patterns

| Pattern | Severity | Auto-fix? |
|---------|----------|-----------|
| `print(` in non-test code | Low | Yes (`--fix`) |
| `breakpoint()` in code | Medium | Yes (`--fix`) |
| Unreachable `if True:` / `if False:` branches | High | Yes (`--fix`) |
| Commented-out code blocks (3+ lines) | Medium | Manual |
| Tests that only assert `mock.called` with no real assertions | High | Manual |
| `if isinstance(x, type) and ...` where type check is redundant | Medium | Manual |

### Output Format

```
scripts/hallucination_remover.py --path .
vault/writer.py:45 — print() statement found (auto-removed)
core/discovery_scheduler.py:201 — unreachable if False branch (manual review)
tests/test_minimax_client.py:112 — gig test: only asserts mock.called (manual review)
```

### CI Integration

Run as part of pre-commit or as a separate GitHub Actions job on PR:

```yaml
# .github/workflows/cleanup-audit.yml
on: [push, pull_request]
jobs:
  hallucination:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python scripts/hallucination_remover.py --path . --fix
      - run: git diff --stat
```

---

## Module Design Blocks

### Module: `vault/junk_cleaner.py`
- **Responsibility:** Detect junk video notes and delete them from vault + vector store
- **Interface:** `cleanup_junk() -> list[str]`
- **Dependencies:** `NOTES_DIR`, `frontmatter`, `VectorStore`
- **Size target:** < 80 lines, single function

### Module: `scripts/hallucination_remover.py`
- **Responsibility:** Static analysis to find dead code, gig tests, and debug artifacts
- **Interface:** CLI with `--path` and `--fix` flags
- **Dependencies:** `ast`, `re` (stdlib only)
- **Size target:** < 200 lines

---

## What Is NOT In Scope

- Cleaning up notes with *partial* transcripts (they have content, even if poor quality)
- Auto-fixing gig tests (requires human judgment on what the test should actually assert)
- Modifying the Obsidian vault format or frontmatter schema
- Any changes to the MiniMax API integration
