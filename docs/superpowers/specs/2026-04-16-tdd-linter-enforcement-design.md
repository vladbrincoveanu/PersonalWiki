# Spec: subagent-driven-development v2 — TDD + Linter Enforcement

**Date:** 2026-04-16
**Status:** Draft

---

## Overview

Evolve `subagent-driven-development` to make TDD hard-required on every task and add a dual-layer linter feedback loop with mandatory self-correction. This is a breaking change to the skill's contract — all projects using it will immediately get stricter enforcement.

---

## 1. TDD Hard Enforcement Gate

### 1.1 No Exceptions

Every task requires TDD. No coverage credit, no "existing tests are good enough." If the feature already works and is tested, the task should be marked complete — not re-implemented with TDD as a ritual.

### 1.2 Ban Mock-Only Assertions

Tests where every assertion is only `.toHaveBeenCalled()` or equivalent (`.toHaveBeenCalledTimes()`, `.toHaveBeenCalledWith()`) are **rejected at RED phase**.

Tests must also assert on:
- Actual return values, or
- State changes on real (non-mock) objects

**Rationale:** A test that only verifies a function was called proves nothing about correctness.

### 1.3 Require Failure Reason in RED

When the test fails (RED phase), the implementer must output:

```
RED: Test failed because [reason]
- Expected: [what test asserted]
- Got: [actual error or value]
- Root cause: [why this happened]
```

### 1.4 Compilation Error = Reject

If the RED phase produces a **compilation error** (not an assertion error), the test is **rejected**. The implementer must fix the test itself — not work around it with `try/catch`, suppression comments, or alternative assertions.

A test that doesn't compile tells you nothing about whether the feature works.

### 1.5 RED Verification

**Mandatory.** After writing the test, run it and confirm:
- Test fails (not errors)
- Failure message matches what the test asserts
- Fails because the feature is missing (not due to typos or environmental issues)

If the test passes immediately, it means the feature already exists or the test doesn't test what it claims. Fix the test.

---

## 2. Dual-Layer Linter Feedback Loop

### 2.1 Post-Commit Auto-Fix Layer (Critical Issues Only)

After the implementer commits, the controller runs a linter on the diff before code quality review begins.

**Auto-fixed without human review:**
- **Syntax / parse errors** — anything preventing compilation or execution
- **Security vulnerabilities** — hardcoded secrets, SQL injection candidates, path traversal, eval usage

These are corrected immediately and automatically.

### 2.2 No-Bypass Rule for Suppressions

The linter enforcement script greps the diff for suppression comments before applying any fixes:

- `// eslint-disable`, `// @ts-ignore`, `//nolint`
- `# noqa`, `# pylint: disable`, `# type: ignore`
- `/* pragma: no cover */`, `// istanbul ignore`
- `// TS_PRAGMA_DISABLE`, `#pragma disable`
- Any equivalent

**If any suppression is found:**
1. The branch is **immediately blocked**
2. The task is flagged for **human review**
3. The AI cannot proceed until a human explicitly approves the suppression

**Rationale:** Prevents the AI from "fixing" linter complaints by silencing warnings rather than fixing the underlying issue.

### 2.3 Code Quality Review Gate (Style / Warnings)

Everything not caught by auto-fix (style violations, unused variables, code complexity, dead code) goes through the code quality reviewer. If the linter found issues, they block approval until resolved.

### 2.4 Linter Selection

- Project has config (`.eslintrc`, `ruff.toml`, `.pylintrc`, `tsconfig.json`) → use project's linter
- No project config → fall back to:
  - **Python:** Ruff
  - **JavaScript/TypeScript:** ESLint
- Controller auto-detects language from project files

---

## 3. Mandatory Self-Correction Pass

Before reporting done, the implementer subagent must run through this checklist and fix any violations found:

| Check | Rule | Action |
|-------|------|--------|
| **Duplication** | 3+ lines repeated verbatim | Extract to shared function |
| **Dead code** | Unused variables, commented-out blocks | Remove |
| **Naming** | Non-descriptive names (x, data, temp, stuff) | Rename to describe purpose |
| **Magic numbers** | Hardcoded literals without constants | Extract to named constant |
| **File size** | File growing beyond its intended scope | Flag as DONE_WITH_CONCERNS |

This is a **mandatory step** — not optional or best-effort. Any violations must be fixed before reporting DONE.

---

## 4. Skill Persistence

**Location:** Plugin cache at `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/subagent-driven-development/`

**Behavior:**
- System-wide — available in every Claude Code session on this machine
- Persists across restarts and sessions
- **Plugin updates will overwrite changes** — re-apply manually after each update

**Rationale:** The plugin cache is local and non-shared. Changes here affect only this machine.

---

## 5. Breaking Change Notice

All projects using `subagent-driven-development` will immediately enforce:
- TDD on every task (no exceptions)
- Dual-layer linter feedback
- Mandatory self-correction

Projects that relied on the looser previous behavior ("follow TDD naturally") will see stricter enforcement.

**Opt-out (not recommended):** Add to project's CLAUDE.md:
```
# Override: subagent-driven-development TDD enforcement disabled
```

---

## 6. Updated Workflow Diagram

```
Per Task:
  Dispatch implementer subagent
        ↓
  [write failing test FIRST] → RED phase
        ↓
  [verify RED: test fails correctly]
        ↓
  [write minimal implementation]
        ↓
  GREEN phase → verify all tests pass
        ↓
  [self-correction checklist] → fix any violations
        ↓
  [commit]
        ↓
  [linter runs on diff]
        ↓
  [suppression grep] → found? → BLOCK for human review
        ↓
  [auto-fix critical errors (syntax, security)]
        ↓
  [dispatch spec reviewer]
        ↓
  [dispatch code quality reviewer] → issues block approval
        ↓
  Mark task complete
```

---

## 7. Files to Modify

- `subagent-driven-development/SKILL.md` — main skill file
- `subagent-driven-development/implementer-prompt.md` — add TDD gate, RED reason requirement, self-correction checklist
- `subagent-driven-development/code-quality-reviewer-prompt.md` — add linter gate, no-bypass rule, suppression check
- `subagent-driven-development/spec-reviewer-prompt.md` — no changes needed

---

## 8. Implementation Notes

### Self-correction automation

The implementer prompt should list the self-correction checklist explicitly. There is no separate script — the implementer applies the checklist manually during self-review before reporting done.

### Linter suppression detection

This is a grep command run by the controller (human or the orchestrating session), not by the subagent:

```bash
# Grep for common suppression patterns in the diff
git diff --cached | grep -iE '(eslint-disable|ts-ignore|noqa|pylint.*disable|pragma.*no.?cover|istanbul.*ignore|type:\s*ignore)'
```

If any match: halt and flag for human review.

### Compilation error detection

The controller should distinguish between:
- **Assertion failure** → RED is correct, proceed to GREEN
- **Syntax/import error** → RED is rejected, send back to fix the test

This distinction matters because a test that can't compile hasn't proven anything about the feature.

---

## 9. Open Questions

None — all resolved during brainstorming.

---

*Self-review: No placeholders, TBDs, or vague requirements. Design is internally consistent. Scope is a single skill evolution — no decomposition needed.*
