# Anti-Bloat Design: Modular Prompting + Automated Refactoring Gates

**Date:** 2026-04-16
**Status:** Approved for implementation

---

## Problem

AI-generated code tends toward:
- **Duplication** — same logic repeated across files/modules
- **Bloat** — oversized functions and modules that do too much
- **Maintenance debt** — 38% code volume increase over time when unchecked

Two complementary solutions:
1. **Modular Prompting** — prevent bloat at generation time
2. **Automated Refactoring Passes** — clean up bloat at finishing time (mandatory gate)

---

## Solution

### Part 1: Modular Prompting at Design Time

**Integration:** `brainstorming` skill → spec document

Every significant module in a spec gets a **Module Design Block**:

```markdown
### Module: <Name>
- **Responsibility:** <One sentence — what it does>
- **Interface:** <Inputs, outputs — what it communicates with>
- **Dependencies:** <What it depends on, if anything>
- **Size target:** <200 lines max, single responsibility — if it needs more, decompose>
```

**Enforcement:** Spec is not approved until all modules have this block filled out. Vague or oversized modules are sent back for clarification.

---

### Part 2: Modular Prompting at Implementation Time

**Integration:** `subagent-driven-development` skill → implementer + spec reviewer

**Implementer checklist per task:**
- Does this task create a new module? If yes, does it have a clear interface?
- Does the module stay under 200 lines? If not, was it intentionally decomposed?
- Does the module have single responsibility? If it does 3+ things, it gets split.

**Spec reviewer gate:**
- Each new/changed module has a clear interface
- No module exceeded 200 lines without documented justification
- No module violates single-responsibility principle
- Violations → code sent back to implementer with specific fix requests

---

### Part 3: Automated Refactoring Gate

**Integration:** `verification-before-completion` AND `finishing-a-development-branch`

Runs automatically after tests pass and before branch can be completed.

**Checks performed:**

| Check | Threshold | Action |
|-------|-----------|--------|
| Module size | > 300 lines | Flag for mandatory split |
| Function complexity | > 3 responsibilities | Flag for refactor |
| DRY — same file | Repeated logic | Auto-fix allowed |
| DRY — same module dir | Repeated logic | Auto-fix allowed |
| DRY — cross-module/domain | Repeated logic | Flag for review only |
| Dead code | Imported but unused | Auto-remove |

**DRY Auto-fix scope rules:**
- **Same file** → auto-extract, inline, deduplicate
- **Same module directory** → auto-extract, inline, deduplicate
- **Different module/domain** → flag with location report, never auto-fix

**Behavior when issues found:**
1. Auto-fix if the fix is mechanical (extract method, remove dead import, inline simple duplication)
2. Flag for review if judgment required (cross-domain duplication, large module split)
3. **Completion blocked** until all flagged issues resolved

---

## Thresholds Summary

| Metric | Soft limit (spec stage) | Hard limit (refactor gate) |
|--------|------------------------|---------------------------|
| Module size | 200 lines | 300 lines — mandatory split |
| Function responsibilities | 3 max | 3 max — flagged |
| DRY (same file/dir) | — | Auto-fix |
| DRY (cross-domain) | — | Review only |

---

## Workflow Example

A typical `finishing-a-development-branch` session:

```
1. Run tests ✅
2. Run refactoring pass
   - Finds 2 same-file DRY violations → auto-fixed
   - Finds "pipeline.py is 480 lines" → flagged for split
   - Finds cross-module duplication in utils/ and services/ → flagged for review
3. User reviews flagged issues
   - Approves pipeline.py split plan
   - Reviews cross-module duplication — decides to keep separate (different domains)
4. Implementer splits pipeline.py, re-runs gate
5. All clear → branch complete ✅
```

---

## Skills Affected

- `brainstorming` — add Module Design Block to spec template
- `subagent-driven-development` — add modular checklist to implementer + spec reviewer prompts
- `verification-before-completion` — add refactoring gate as mandatory step
- `finishing-a-development-branch` — add refactoring gate as mandatory step

---

## Out of Scope

- Automated fixes for cross-module/domain DRY violations (always review)
- Changes to `test-driven-development` skill (already has strong generation-time checks)
- Scheduling/recurring background refactoring passes
