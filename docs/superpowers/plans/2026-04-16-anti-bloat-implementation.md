# Anti-Bloat Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate modular prompting at design/implementation time and automated refactoring gate at finishing time into superpower skills.

**Architecture:** Modify 5 skill files to add anti-bloat checks at generation time (brainstorming, subagent-driven-development) and finishing time (verification-before-completion, finishing-a-development-branch). No new files created.

**Tech Stack:** Superpower skill markdown files.

---

## File Structure

| Skill File | Change |
|------------|--------|
| `brainstorming/SKILL.md` | Add Module Design Block requirement to spec template |
| `subagent-driven-development/implementer-prompt.md` | Add modular checklist before self-review |
| `subagent-driven-development/spec-reviewer-prompt.md` | Add modular compliance checks |
| `verification-before-completion/SKILL.md` | Add refactoring gate as mandatory step after tests pass |
| `finishing-a-development-branch/SKILL.md` | Add refactoring gate as mandatory step after tests pass |

**Base path:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/`

---

## Task 1: Add Module Design Block to brainstorming Skill

**Files:**
- Modify: `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/brainstorming/SKILL.md`

- [ ] **Step 1: Read current brainstorming SKILL.md section on spec writing**

Open the file and find the section where spec documents are described (around line 107-114 in the "After the Design" section).

- [ ] **Step 2: Add Module Design Block to spec template**

In the "Spec Self-Review" section, after the existing spec structure guidance, add:

```markdown
## Module Design Block Requirement

Every significant module in a spec MUST have a Module Design Block:

```markdown
### Module: <Name>
- **Responsibility:** <One sentence — what it does>
- **Interface:** <Inputs, outputs — what it communicates with>
- **Dependencies:** <What it depends on, if anything>
- **Size target:** <200 lines max, single responsibility — if it needs more, decompose>
```

**Enforcement:** A spec is NOT approved until all modules have this block filled out. Vague or oversized modules are sent back for clarification before proceeding.
```

- [ ] **Step 3: Commit**

```bash
git add ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/brainstorming/SKILL.md
git commit -m "feat(brainstorming): add Module Design Block requirement to spec template

All significant modules must now document responsibility, interface,
dependencies, and size target before spec approval.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Add Modular Checklist to implementer-prompt

**Files:**
- Modify: `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/subagent-driven-development/implementer-prompt.md`

- [ ] **Step 1: Read current implementer-prompt.md self-review section**

Find the "Before Reporting Back: Self-Review" section (around lines 74-98).

- [ ] **Step 2: Add modular checklist to self-review section**

After the existing self-review questions, add a new "Modular Checklist" subsection:

```markdown
    **Modular Checklist (Anti-Bloat):**
    - Does each new module have a clear interface (inputs, outputs, dependencies)?
    - Does each module stay under 200 lines? If not, was it intentionally decomposed?
    - Does each module have single responsibility (one reason to change)?
    - Did I avoid duplicating logic that already exists in the codebase?
    - If I copied code from elsewhere, did I extract a shared helper instead?

    If any answer is "no" → fix before reporting back.
```

- [ ] **Step 3: Commit**

```bash
git add ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/subagent-driven-development/implementer-prompt.md
git commit -m "feat(subagent-driven): add modular checklist to implementer self-review

Anti-bloat checklist ensures modules stay small, single-responsibility,
and DRY before code is submitted for review.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Add Modular Checks to spec-reviewer-prompt

**Files:**
- Modify: `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/subagent-driven-development/spec-reviewer-prompt.md`

- [ ] **Step 1: Read current spec-reviewer-prompt.md**

Note the structure: "Your Job" section lists what to verify. This is where we add modular checks.

- [ ] **Step 2: Add modular compliance checks**

After the existing "Your Job" section content, add:

```markdown
    **Modular Compliance (Anti-Bloat):**
    - Does each new/changed module have a clear interface documented?
    - Did any module exceed 200 lines without documented justification?
    - Did any module violate single-responsibility (doing 3+ unrelated things)?
    - Did the implementer check for DRY before submitting?

    **DRY enforcement:**
    - Same-file duplication → implementer must auto-fix before review
    - Same-module duplication → implementer must auto-fix before review
    - Cross-module/domain duplication → flag for review, do NOT auto-fix

    Violations → code sent back to implementer with specific fix requests.
```

- [ ] **Step 3: Update report format to include modular assessment**

In the report format at the bottom, add a "Modular Compliance" line:

```
    Report:
    - ✅ Spec compliant + modular compliant (if everything checks out)
    - ✅ Spec compliant, modular issues found: [list with file:line references]
    - ❌ Spec issues found: [list with file:line references]
```

- [ ] **Step 4: Commit**

```bash
git add ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/subagent-driven-development/spec-reviewer-prompt.md
git commit -m "feat(subagent-driven): add modular compliance checks to spec reviewer

Spec reviewer now verifies module size, single-responsibility, and DRY
compliance. Cross-module duplication is flagged for review only.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Add Refactoring Gate to verification-before-completion

**Files:**
- Modify: `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/verification-before-completion/SKILL.md`

- [ ] **Step 1: Read current verification-before-completion SKILL.md**

Note the structure: "The Gate Function" section is the core logic. We add refactoring checks after tests pass.

- [ ] **Step 2: Add refactoring gate section after test verification**

After the existing test verification pattern (line ~79-82 "Tests:"), add a new "Refactoring Gate" section before "Common Failures":

```markdown
## Refactoring Gate (Anti-Bloat)

After tests pass, run the refactoring gate BEFORE claiming completion.

**Thresholds:**

| Check | Threshold | Action |
|-------|-----------|--------|
| Module size | > 300 lines | Flag for mandatory split |
| Function complexity | > 3 responsibilities | Flag for refactor |
| DRY — same file | Repeated logic | Auto-fix |
| DRY — same module dir | Repeated logic | Auto-fix |
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

**How to run the gate:**
- Use the simplify skill or code review subagent to scan changed files
- For DRY checks: search for repeated function/class patterns across modified files
- Report what was found, what was auto-fixed, and what needs review
```

- [ ] **Step 3: Commit**

```bash
git add ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/verification-before-completion/SKILL.md
git commit -m "feat(verification): add mandatory refactoring gate to verification skill

Refactoring gate runs after tests pass. Auto-fixes same-file/module DRY
violations. Flags cross-module duplication for review. Blocks completion
until all issues resolved.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Add Refactoring Gate to finishing-a-development-branch

**Files:**
- Modify: `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/finishing-a-development-branch/SKILL.md`

- [ ] **Step 1: Read current finishing-a-development-branch SKILL.md**

Note the structure: Step 1 is "Verify Tests". We insert refactoring gate between Step 1 and Step 2.

- [ ] **Step 2: Rename existing step structure to insert refactoring gate**

Replace "### Step 1: Verify Tests" section with:

```markdown
### Step 1: Verify Tests

**Before presenting options, verify tests pass:**

```bash
# Run project's test suite
npm test / cargo test / pytest / go test ./...
```

**If tests fail:**
```
Tests failing (<N> failures). Must fix before completing:

[Show failures]

Cannot proceed with merge/PR until tests pass.
```

Stop. Don't proceed to Step 2.

**If tests pass:** Continue to Step 2.

### Step 2: Refactoring Gate (Anti-Bloat)

**After tests pass, run refactoring gate BEFORE presenting merge options:**

Run a scan of all changed files since the feature branch split:

- **Module size (>300 lines):** List files exceeding hard limit
- **Function complexity (>3 responsibilities):** Flag complex functions
- **DRY same-file/dir:** Auto-fix repeated logic
- **DRY cross-module:** Flag locations for review
- **Dead imports:** Auto-remove

**Report format:**
```
Refactoring Gate Results:
- [Auto-fixed] N same-file DRY violations
- [Auto-fixed] N dead import removals
- [Flagged] N module size issues — review before merge
- [Flagged] N cross-module duplications — review before merge
```

**If any flagged issues:** Present them to user for review decision before proceeding.

**If all clear or user approves flagged issues:** Continue to Step 3.

### Step 3: Determine Base Branch
```

(And renumber subsequent steps: Step 3 → Step 4, Step 4 → Step 5, Step 5 → Step 6)

- [ ] **Step 3: Commit**

```bash
git add ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/finishing-a-development-branch/SKILL.md
git commit -m "feat(finishing): add mandatory refactoring gate before merge options

Refactoring gate runs after tests pass, before presenting merge options.
Auto-fixes same-file/module DRY. Flags cross-module issues for review.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Part 1 (brainstorming Module Design Block) → Task 1
- [x] Part 2 (implementer modular checklist) → Task 2
- [x] Part 2 (spec reviewer modular checks) → Task 3
- [x] Part 3 (verification-before-completion refactoring gate) → Task 4
- [x] Part 3 (finishing-a-development-branch refactoring gate) → Task 5
- [x] DRY auto-fix scope (same file/dir only) → enforced in Tasks 3, 4, 5
- [x] Thresholds (200 soft, 300 hard) → consistent across Tasks 1, 2, 3, 4, 5
- [x] Blocking completion until issues resolved → Tasks 4, 5

**Placeholder scan:** No TBDs, TODOs, or vague requirements. All thresholds, actions, and file paths are explicit.

**Type consistency:** All skill references use exact paths and skill names consistent with existing files.
