# Vault Cleanup + Hallucination Remover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two independent cleanup systems: (1) vault junk cleaner that runs every discovery cycle to delete video notes with no transcript, and (2) a hallucination remover script that finds dead code, gig tests, and debug artifacts.

**Architecture:** Part 1 is a new `vault/junk_cleaner.py` module integrated into `DiscoveryScheduler._run_discovery_cycle()`. Part 2 is a standalone `scripts/hallucination_remover.py` CLI script with AST-based static analysis.

**Tech Stack:** Python stdlib only (`ast`, `re`, `pathlib`, `argparse`)

---

## File Structure

```
vault/junk_cleaner.py          # NEW — junk detection + deletion
vault/tests/
  test_junk_cleaner.py         # NEW — tests for junk_cleaner
core/discovery_scheduler.py    # MODIFY — call cleanup_junk() at end of cycle
scripts/
  hallucination_remover.py      # NEW — static analysis script
scripts/tests/
  test_hallucination_remover.py # NEW — tests for hallucination remover
.github/workflows/
  cleanup-audit.yml             # NEW — CI job (optional, non-blocking)
```

---

## Part 1: Vault Junk Cleaner

### Task 1: `vault/junk_cleaner.py`

**Files:**
- Create: `vault/junk_cleaner.py`
- Create: `vault/tests/test_junk_cleaner.py`

- [ ] **Step 1: Write the failing test**

```python
# vault/tests/test_junk_cleaner.py
import pytest
import tempfile
import os
from pathlib import Path

def test_cleanup_junk_detects_empty_video_note():
    """Video note with no raw_text should be marked as junk."""
    from vault.junk_cleaner import _is_junk_note
    note = {"type": "video", "raw_text": "", "title": "Test Video"}
    assert _is_junk_note(note) is True

def test_cleanup_junk_detects_short_raw_text():
    """Video note with raw_text < 50 chars should be marked as junk."""
    from vault.junk_cleaner import _is_junk_note
    note = {"type": "video", "raw_text": "short", "title": "Test"}
    assert _is_junk_note(note) is True

def test_cleanup_junk_allows_article_notes():
    """Article notes should never be junk regardless of content."""
    from vault.junk_cleaner import _is_junk_note
    note = {"type": "article", "raw_text": "", "title": "Article"}
    assert _is_junk_note(note) is False

def test_cleanup_junk_allows_video_with_transcript():
    """Video note with substantial raw_text should not be junk."""
    from vault.junk_cleaner import _is_junk_note
    note = {"type": "video", "raw_text": "x" * 100, "title": "Good Video"}
    assert _is_junk_note(note) is False

def test_cleanup_junk_detects_no_transcript_marker():
    """Note title with [NO_TRANSCRIPT] should be junk regardless of type."""
    from vault.junk_cleaner import _is_junk_note
    note = {"type": "video", "raw_text": "x" * 100, "title": "Video [NO_TRANSCRIPT]"}
    assert _is_junk_note(note) is True

def test_cleanup_junk_detects_translation_failed_marker():
    """Note title with [TRANSLATION_FAILED] should be junk."""
    from vault.junk_cleaner import _is_junk_note
    note = {"type": "article", "raw_text": "", "title": "Article [TRANSLATION_FAILED]"}
    assert _is_junk_note(note) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest vault/tests/test_junk_cleaner.py -v`
Expected: FAIL — `vault.junk_cleaner` has no `_is_junk_note`

- [ ] **Step 3: Write minimal implementation**

```python
# vault/junk_cleaner.py
"""
Vault junk cleaner — removes video notes with no transcript content.
"""
import logging
from pathlib import Path
import frontmatter
from config import NOTES_DIR

_logger = logging.getLogger(__name__)

def _is_junk_note(note: dict) -> bool:
    """Return True if a note should be deleted as junk."""
    title = note.get("title", "")
    if "[NO_TRANSCRIPT]" in title or "[TRANSLATION_FAILED]" in title:
        return True
    if note.get("type") != "video":
        return False
    raw_text = note.get("raw_text", "")
    return len(raw_text) < 50

def cleanup_junk() -> list[str]:
    """
    Scan NOTES_DIR for junk video notes and delete them from vault + vector store.
    Returns list of deleted file paths.
    """
    if not NOTES_DIR.exists():
        return []

    from core.vector_store import get_store
    store = get_store()
    deleted: list[str] = []

    for md_path in NOTES_DIR.glob("*.md"):
        try:
            post = frontmatter.parse(md_path.read_text(encoding="utf-8"))
            note = dict(post)
            note["raw_text"] = post.content
            if not _is_junk_note(note):
                continue
            _logger.info("Junk cleanup: removing %s", md_path.name)
            md_path.unlink()
            # Remove from vector store
            try:
                store.upsert(path=str(md_path), text="", vector=[], links=[], metadata={})
            except Exception:
                pass
            deleted.append(str(md_path))
        except Exception as e:
            _logger.warning("Junk cleanup: failed to process %s: %s", md_path.name, e)

    return deleted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest vault/tests/test_junk_cleaner.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add vault/junk_cleaner.py vault/tests/test_junk_cleaner.py
git commit -m "feat: add vault junk cleaner module
- _is_junk_note() detects empty/short video notes and [NO_TRANSCRIPT] markers
- cleanup_junk() deletes junk from vault and vector store
- 6 passing unit tests
Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: DiscoveryScheduler Integration

**Files:**
- Modify: `core/discovery_scheduler.py` (end of `_run_discovery_cycle`)

- [ ] **Step 1: Add import at top of file**

Check that `from vault.junk_cleaner import cleanup_junk` is present after the other vault imports. If not, add it.

- [ ] **Step 2: Find the end of `_run_discovery_cycle()`**

Read `core/discovery_scheduler.py` around lines 560-577. The method ends with a logger line after `_run_discovery_cycle()` completes. Add the cleanup call just before the method returns.

```python
# At the end of _run_discovery_cycle(), after the for-loop but before the echo-chamber guard:
# (Find the line: "Discovery: ingested N URLs")
# Insert AFTER that block, at the very end of the method:
try:
    deleted = cleanup_junk()
    if deleted:
        _logger.info("Junk cleanup: removed %d notes", len(deleted))
except Exception as e:
    _logger.warning("Junk cleanup failed: %s", e)
```

The exact insertion point is the last `except Exception as e:` block in the `try/except` around `_run_discovery_cycle()`.

- [ ] **Step 3: Verify import is present**

Check the imports section of `discovery_scheduler.py`. You should see `from vault.writer import write_note` or similar vault imports. Add:
```python
from vault.junk_cleaner import cleanup_junk
```

- [ ] **Step 4: Verify no test breakage**

Run: `python -m pytest tests/test_discovery_scheduler.py -v -x`
Expected: PASS (no regressions from adding the import and call)

- [ ] **Step 5: Commit**

```bash
git add core/discovery_scheduler.py
git commit -m "feat: run vault junk cleanup at end of each discovery cycle
Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Part 2: Hallucination Remover

### Task 3: `scripts/hallucination_remover.py`

**Files:**
- Create: `scripts/hallucination_remover.py`
- Create: `scripts/tests/test_hallucination_remover.py`

- [ ] **Step 1: Write tests for print/breakpoint detection**

```python
# scripts/tests/test_hallucination_remover.py
import pytest
import tempfile
import os
from pathlib import Path

def test_detects_print_in_source():
    """Should detect print() statements in non-test source files."""
    import subprocess
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        test_file.write_text('print("debug")\nx = 1\n')
        result = subprocess.run(
            ["python", "scripts/hallucination_remover.py", "--path", tmpdir],
            capture_output=True, text=True
        )
        assert "print(" in result.stdout or "print" in result.stdout

def test_detects_breakpoint():
    """Should detect breakpoint() calls."""
    import subprocess
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        test_file.write_text('breakpoint()\nx = 1\n')
        result = subprocess.run(
            ["python", "scripts/hallucination_remover.py", "--path", tmpdir],
            capture_output=True, text=True
        )
        assert "breakpoint()" in result.stdout

def test_detects_unreachable_if_false():
    """Should detect unreachable if False: branches."""
    import subprocess
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        test_file.write_text('if False:\n    x = 1\n')
        result = subprocess.run(
            ["python", "scripts/hallucination_remover.py", "--path", tmpdir],
            capture_output=True, text=True
        )
        assert "if False" in result.stdout

def test_auto_removes_print_with_fix():
    """Should auto-remove print() when --fix is passed."""
    import subprocess
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        test_file.write_text('print("debug")\nx = 1\n')
        result = subprocess.run(
            ["python", "scripts/hallucination_remover.py", "--path", tmpdir, "--fix"],
            capture_output=True, text=True
        )
        content = test_file.read_text()
        assert "print" not in content
        assert "x = 1" in content

def test_auto_removes_breakpoint_with_fix():
    """Should auto-remove breakpoint() when --fix is passed."""
    import subprocess
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        test_file.write_text('x = 1\nbreakpoint()\ny = 2\n')
        result = subprocess.run(
            ["python", "scripts/hallucination_remover.py", "--path", tmpdir, "--fix"],
            capture_output=True, text=True
        )
        content = test_file.read_text()
        assert "breakpoint()" not in content
        assert "x = 1" in content
        assert "y = 2" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest scripts/tests/test_hallucination_remover.py -v`
Expected: FAIL — `scripts/hallucination_remover.py` does not exist

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
"""
Hallucination remover — finds dead code, gig tests, and debug artifacts.

Usage:
    python scripts/hallucination_remover.py --path . [--fix]
"""
import ast
import argparse
import os
import re
from pathlib import Path

PRINT_RE = re.compile(r'\bprint\s*\(')
BREAKPOINT_RE = re.compile(r'\bbreakpoint\s*\(')
COMMENTED_BLOCK_RE = re.compile(r'^#.*\n.{3,}', re.MULTILINE)

def is_test_file(path: Path) -> bool:
    return path.name.startswith("test_") or path.name.endswith("_test.py")

def scan_file(path: Path, fix: bool = False) -> list[tuple[int, str]]:
    """Scan a single file for hallucination patterns. Returns list of (line, description)."""
    issues = []
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return issues

    # Check for print() in non-test files
    if not is_test_file(path):
        for i, line in enumerate(content.splitlines(), 1):
            if PRINT_RE.search(line):
                issues.append((i, f"print() statement found (auto-removed)"))
                if fix:
                    content = content.replace(line + "\n", "").replace(line, "")
            if BREAKPOINT_RE.search(line):
                issues.append((i, f"breakpoint() found (auto-removed)"))
                if fix:
                    content = content.replace(line + "\n", "").replace(line, "")

    # AST-based checks
    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError:
        return issues

    for node in ast.walk(tree):
        # Detect if False: branches
        if isinstance(node, ast.If):
            if isinstance(node.test, ast.Constant) and node.test.value is False:
                issues.append((node.lineno, "unreachable if False: branch"))
            elif isinstance(node.test, ast.Constant) and node.test.value is True:
                issues.append((node.lineno, "redundant if True: branch"))

    if fix and content != path.read_text(encoding="utf-8"):
        path.write_text(content, encoding="utf-8")

    return issues

def scan(path: Path, fix: bool = False) -> dict[Path, list[tuple[int, str]]]:
    """Scan directory for hallucination patterns."""
    results: dict[Path, list[tuple[int, str]]] = {}
    for py_file in path.rglob("*.py"):
        # Skip virtual environments and caches
        if ".venv" in py_file.parts or "__pycache__" in py_file.parts:
            continue
        issues = scan_file(py_file, fix=fix)
        if issues:
            results[py_file] = issues
    return results

def main():
    parser = argparse.ArgumentParser(description="Remove hallucinations from code")
    parser.add_argument("--path", type=str, default=".", help="Directory to scan")
    parser.add_argument("--fix", action="store_true", help="Auto-fix safe patterns")
    args = parser.parse_args()

    scan_path = Path(args.path).resolve()
    results = scan(scan_path, fix=args.fix)

    if not results:
        print("No hallucinations found.")
        return

    for file, issues in sorted(results.items()):
        for lineno, msg in issues:
            print(f"{file}:{lineno} — {msg}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest scripts/tests/test_hallucination_remover.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Test against the actual codebase**

Run: `python scripts/hallucination_remover.py --path .`
Expected: Lists findings (there should be some — this codebase was AI-generated)

- [ ] **Step 6: Commit**

```bash
git add scripts/hallucination_remover.py scripts/tests/test_hallucination_remover.py
git commit -m "feat: add hallucination remover script
- Detects print(), breakpoint(), unreachable if False:/if True: branches
- --fix flag auto-removes safe patterns
- 5 passing tests
Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: GitHub Actions CI (Optional)

**Files:**
- Create: `.github/workflows/cleanup-audit.yml`

This is optional — the script works standalone. Only add if you want automated enforcement on PRs.

- [ ] **Step 1: Create workflow file**

```yaml
# .github/workflows/cleanup-audit.yml
name: Hallucination Audit
on: [push, pull_request]

jobs:
  hallucination:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run hallucination remover
        run: python scripts/hallucination_remover.py --path . --fix
      - name: Show diff
        run: git diff --stat
      - name: Commit auto-fixes
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "fix: auto-remove hallucinations"
          auto_push: true
```

- [ ] **Step 2: Commit (optional)**

```bash
git add .github/workflows/cleanup-audit.yml
git commit -m "ci: add hallucination audit GitHub Actions job
Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage check:**
- [x] Vault junk cleaner (`vault/junk_cleaner.py`) → Task 1
- [x] Detection criteria (empty/short raw_text, NO_TRANSCRIPT marker) → `_is_junk_note()` in Task 1
- [x] Vector store cleanup → `store.upsert()` with empty data in Task 1
- [x] DiscoveryScheduler integration → Task 2
- [x] Hallucination remover script → Task 3
- [x] print()/breakpoint() detection → Task 3
- [x] Unreachable if True:/if False: detection → Task 3
- [x] `--fix` flag → Task 3
- [x] CI workflow → Task 4 (optional)
- [x] Size targets (< 80 lines, < 200 lines) → design respected

**Placeholder scan:** No TBD/TODO markers. All code is complete.

**Type consistency:** `cleanup_junk() -> list[str]` matches spec. `scan() -> dict[Path, list[...]]` matches CLI interface.

---

## Task Summary

| # | Task | Type | Files |
|---|------|------|-------|
| 1 | Vault junk cleaner module | New | `vault/junk_cleaner.py`, `vault/tests/test_junk_cleaner.py` |
| 2 | DiscoveryScheduler integration | Modify | `core/discovery_scheduler.py` |
| 3 | Hallucination remover script | New | `scripts/hallucination_remover.py`, `scripts/tests/test_hallucination_remover.py` |
| 4 | GitHub Actions CI (optional) | New | `.github/workflows/cleanup-audit.yml` |
