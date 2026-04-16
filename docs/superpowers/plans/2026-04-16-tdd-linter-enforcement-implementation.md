# TDD + Linter Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve subagent-driven-development skill to enforce TDD hard, add dual-layer linter feedback loop, and mandate self-correction before reporting done.

**Architecture:** Modify three files in the plugin cache: SKILL.md (main workflow + rules), implementer-prompt.md (subagent instructions), code-quality-reviewer-prompt.md (linter gate). No new files — all changes are in-place edits to existing templates.

**Tech Stack:** Claude Code skill system (Markdown YAML frontmatter)

---

## File Map

| File | Role |
|------|------|
| `~/.claude/plugins/cache/.../subagent-driven-development/SKILL.md` | Main skill — workflow, rules, integration |
| `~/.claude/plugins/cache/.../subagent-driven-development/implementer-prompt.md` | Template dispatched to implementer subagent |
| `~/.claude/plugins/cache/.../subagent-driven-development/code-quality-reviewer-prompt.md` | Template dispatched to code quality reviewer |

---

## Task 1: Update SKILL.md — Main Workflow and Rules

**File:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/subagent-driven-development/SKILL.md`

**Changes:** Replace the current "Subagents should use superpowers:test-driven-development" with hard TDD enforcement, add the dual-layer linter loop, add no-bypass rule, update self-review to mandatory checklist, update diagram.

- [ ] **Step 1: Replace TDD "should" with hard "must" in the integration section**

Find (around line 268):
```
**Subagents should use:**
- **superpowers:test-driven-development** - Subagents follow TDD for each task
```

Replace with:
```
**Subagents MUST use:**
- **superpowers:test-driven-development** - TDD is hard-required on every task, no exceptions. The implementer must write a failing test first, verify RED, write minimal code, verify GREEN. No implementation code accepted before a failing test. See TDD Hard Enforcement Gate below.
```

- [ ] **Step 2: Add TDD Hard Enforcement Gate section after the process diagram**

After the "## Handling Implementer Status" section (around line 126), add:

```
## TDD Hard Enforcement Gate

Every task MUST follow TDD. No exceptions — not even when existing tests cover the feature, the code seems simple, or time is short.

### Rules

**1. Mock-only assertions are banned.**
Tests where every assertion is only `.toHaveBeenCalled()` or equivalent are rejected at RED phase. Tests must also assert on:
- Actual return values, or
- State changes on real (non-mock) objects

**2. RED phase requires failure reason output.**
When the test fails, the implementer must output:
```
RED: Test failed because [reason]
- Expected: [what test asserted]
- Got: [actual error or value]
- Root cause: [why this happened]
```

**3. Compilation error = reject.**
If RED produces a compilation error (not an assertion error), the test is rejected. The implementer must fix the test itself — not work around it with try/catch or suppression comments.

**4. Suppression comments block the branch.**
Before any linter auto-fix, the diff is grepped for suppression patterns (`// eslint-disable`, `// @ts-ignore`, `# noqa`, `# pylint: disable`, `/* pragma: no cover */`, etc.). If any are found, the branch is immediately blocked and flagged for human review.

### No-Bypass Rule

The AI cannot decide a linter warning is acceptable. If a suppression comment is found in the diff, the task is flagged for human review and cannot proceed until explicitly approved. This prevents the AI from "fixing" complaints by silencing them rather than fixing the underlying issue.
```

- [ ] **Step 3: Update the process diagram to show linter post-commit**

Find the existing `digraph process` (around line 42). Replace the per-task section with:

```
subgraph cluster_per_task {
    label="Per Task";
    "Dispatch implementer subagent (./implementer-prompt.md)" [shape=box];
    "Implementer subagent asks questions?" [shape=diamond];
    "Answer questions, provide context" [shape=box];
    "Implementer subagent writes failing test FIRST" [shape=box];
    "RED phase: verify failure reason output" [shape=box];
    "Implementer subagent implements, tests, commits, self-reviews" [shape=box];
    "Dispatch spec reviewer subagent (./spec-reviewer-prompt.md)" [shape=box];
    "Spec reviewer subagent confirms code matches spec?" [shape=diamond];
    "Implementer subagent fixes spec gaps" [shape=box];
    "Dispatch code quality reviewer subagent (./code-quality-reviewer-prompt.md)" [shape=box];
    "Code quality reviewer subagent approves?" [shape=diamond];
    "Implementer subagent fixes quality issues" [shape=box];
    "Mark task complete in TodoWrite" [shape=box];
}

"Dispatch implementer subagent (./implementer-prompt.md)" -> "Implementer subagent asks questions?";
"Implementer subagent asks questions?" -> "Answer questions, provide context" [label="yes"];
"Answer questions, provide context" -> "Dispatch implementer subagent (./implementer-prompt.md)";
"Implementer subagent asks questions?" -> "Implementer subagent writes failing test FIRST" [label="no"];
"Implementer subagent writes failing test FIRST" -> "RED phase: verify failure reason output";
"RED phase: verify failure reason output" -> "Implementer subagent implements, tests, commits, self-reviews";
"Implementer subagent implements, tests, commits, self-reviews" -> "Dispatch spec reviewer subagent (./spec-reviewer-prompt.md)";
"Dispatch spec reviewer subagent (./spec-reviewer-prompt.md)" -> "Spec reviewer subagent confirms code matches spec?";
"Spec reviewer subagent confirms code matches spec?" -> "Implementer subagent fixes spec gaps" [label="no"];
"Implementer subagent fixes spec gaps" -> "Dispatch spec reviewer subagent (./spec-reviewer-prompt.md)" [label="re-review"];
"Spec reviewer subagent confirms code matches spec?" -> "Dispatch code quality reviewer subagent (./code-quality-reviewer-prompt.md)" [label="yes"];
"Dispatch code quality reviewer subagent (./code-quality-reviewer-prompt.md)" -> "Code quality reviewer subagent approves?";
"Code quality reviewer subagent approves?" -> "Implementer subagent fixes quality issues" [label="no"];
"Implementer subagent fixes quality issues" -> "Dispatch code quality reviewer subagent (./code-quality-reviewer-prompt.md)" [label="re-review"];
"Code quality reviewer subagent approves?" -> "Mark task complete in TodoWrite" [label="yes"];
```

- [ ] **Step 4: Update self-review section to mandatory checklist**

Find "## Before Reporting Back: Self-Review" (around line 74). Replace with:

```
## Mandatory Self-Correction Pass

Before reporting done, you MUST run through this checklist and fix any violations found:

| Check | Rule | Action |
|-------|------|--------|
| **Duplication** | 3+ lines repeated verbatim | Extract to shared function |
| **Dead code** | Unused variables, commented-out blocks | Remove |
| **Naming** | Non-descriptive names (x, data, temp, stuff) | Rename to describe purpose |
| **Magic numbers** | Hardcoded literals without constants | Extract to named constant |
| **File size** | File growing beyond its intended scope | Flag as DONE_WITH_CONCERNS |

This is a mandatory step — not optional. Fix any violations before reporting DONE.
```

- [ ] **Step 5: Add breaking change notice**

After the "## Integration" section (line 265), add:

```
## Breaking Change Notice

This version of subagent-driven-development enforces TDD as a hard requirement and adds linter feedback loops. All projects using this skill will immediately see stricter enforcement:

- TDD cannot be skipped for any task
- Mock-only assertions are rejected
- Suppression comments block the branch
- Self-correction checklist is mandatory

Projects that need looser behavior can add to their CLAUDE.md:
```
# Override: subagent-driven-development TDD enforcement disabled
```

**Recommended:** Use the strict enforcement. The original "follow TDD naturally" was insufficient to prevent AI-generated code errors.
```

- [ ] **Step 6: Add linter post-commit step to workflow sequence**

Find the sequence after "Mark task complete in TodoWrite" (line 80). Add post-commit linter step before the "More tasks remain?" diamond:

```
"Mark task complete in TodoWrite" -> "Post-commit linter check";
"Post-commit linter check" [shape=box, label="Run linter on diff\nSuppression grep → blocked?\nAuto-fix critical errors"];
"Post-commit linter check" -> "More tasks remain?";
```

- [ ] **Step 7: Update Advantages and Red Flags sections**

In "## Advantages", find:
```
**vs. Manual execution:**
- Subagents follow TDD naturally
```

Replace with:
```
**vs. Manual execution:**
- Subagents enforce TDD hard — no skipping, no rationalizations
```

In "## Red Flags", ensure these are present (add if missing):
```
- Writing implementation code before a failing test
- Reporting DONE without running the self-correction checklist
- Accepting a test that only asserts mock calls (no state/return assertions)
- Allowing suppression comments instead of fixing the underlying issue
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(subagent-driven-development): add TDD hard enforcement and linter feedback loop

- TDD mandatory on every task, no exceptions
- Mock-only assertions banned at RED phase
- RED phase requires failure reason output
- Compilation error = reject test, not implementation
- Suppression comments block branch for human review
- Mandatory self-correction checklist before reporting done
- Post-commit linter with critical-error auto-fix
- Breaking change: all projects get stricter enforcement

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Update implementer-prompt.md — Subagent Instructions

**File:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/subagent-driven-development/implementer-prompt.md`

**Changes:** Expand the template with TDD enforcement gate details, RED phase requirements, and mandatory self-correction checklist.

- [ ] **Step 1: Replace the entire implementer-prompt.md content**

The current template is brief. Replace it with the full expanded version:

```markdown
# Implementer Subagent Prompt Template

Use this template when dispatching an implementer subagent.

```
Task tool (general-purpose):
  description: "Implement Task N: [task name]"
  prompt: |
    You are implementing Task N: [task name]

    ## Task Description

    [FULL TEXT of task from plan - paste it here, don't make subagent read file]

    ## Context

    [Scene-setting: where this fits, dependencies, architectural context]

    ## CRITICAL: TDD Is Hard-Required

    **You MUST follow TDD on this task. No exceptions.**

    This is not "follow TDD naturally" — it is enforced. If you write implementation code
    before a failing test, your work will be rejected and sent back.

    ### TDD Gate Rules

    **1. Write the failing test FIRST.**
    Before writing any implementation code, write a test that demonstrates the missing behavior.

    **2. Mock-only assertions are banned.**
    Your test cannot only assert `.toHaveBeenCalled()` or equivalent. You must also assert:
    - Actual return values, OR
    - State changes on real (non-mock) objects

    A test that only verifies a function was called proves nothing about correctness.

    **3. RED phase — output failure reason.**
    After running the test and watching it fail, output:
    ```
    RED: Test failed because [reason]
    - Expected: [what test asserted]
    - Got: [actual error or value]
    - Root cause: [why this happened]
    ```

    **4. Compilation error = reject the test.**
    If your test fails with a compilation error (not an assertion error), fix the TEST — not the
    implementation. A test that doesn't compile tells you nothing about whether the feature works.
    Do NOT use try/catch, suppression comments, or workarounds to bypass this.

    ## Before You Begin

    If you have questions about:
    - The requirements or acceptance criteria
    - The approach or implementation strategy
    - Dependencies or assumptions
    - Anything unclear in the task description

    **Ask them now.** Raise any concerns before starting work.

    ## Your Job

    Once you're clear on requirements:
    1. Write a failing test demonstrating the missing behavior (RED)
    2. Run the test and verify it fails for the right reason — output the failure reason
    3. Write minimal implementation to pass the test (GREEN)
    4. Run tests and verify all pass
    5. Run self-correction checklist (below) — fix any violations
    6. Commit your work
    7. Report back

    Work from: [directory]

    **While you work:** If you encounter something unexpected or unclear, **ask questions**.
    It's always OK to pause and clarify. Don't guess or make assumptions.

    ## Mandatory Self-Correction Checklist

    Before reporting done, you MUST check and fix:

    | Check | Rule | Action if found |
    |-------|------|-----------------|
    | **Duplication** | 3+ lines repeated verbatim | Extract to shared function |
    | **Dead code** | Unused variables, commented-out blocks | Remove |
    | **Naming** | Non-descriptive names (x, data, temp, stuff) | Rename to describe purpose |
    | **Magic numbers** | Hardcoded literals without constants | Extract to named constant |
    | **File size** | File growing beyond its intended scope | Flag in report as DONE_WITH_CONCERNS |

    This is mandatory. Not optional.

    ## Code Organization

    You reason best about code you can hold in context at once, and your edits are more
    reliable when files are focused. Keep this in mind:
    - Follow the file structure defined in the plan
    - Each file should have one clear responsibility with a well-defined interface
    - If a file you're creating is growing beyond the plan's intent, stop and report
      it as DONE_WITH_CONCERNS — don't split files on your own without plan guidance
    - If an existing file you're modifying is already large or tangled, work carefully
      and note it as a concern in your report
    - In existing codebases, follow established patterns. Improve code you're touching
      the way a good developer would, but don't restructure things outside your task.

    ## When You're in Over Your Head

    It is always OK to stop and say "this is too hard for me." Bad work is worse than
    no work. You will not be penalized for escalating.

    **STOP and escalate when:**
    - The task requires architectural decisions with multiple valid approaches
    - You need to understand code beyond what was provided and can't find clarity
    - You feel uncertain about whether your approach is correct
    - The task involves restructuring existing code in ways the plan didn't anticipate
    - You've been reading file after file trying to understand the system without progress

    **How to escalate:** Report back with status BLOCKED or NEEDS_CONTEXT. Describe
    specifically what you're stuck on, what you've tried, and what kind of help you need.
    The controller can provide more context, re-dispatch with a more capable model,
    or break the task into smaller pieces.

    ## Before Reporting Back

    Review your work with fresh eyes. Ask yourself:

    **TDD Discipline:**
    - Did I write a failing test BEFORE writing implementation code?
    - Does my test assert on actual behavior (return values or state), not just mock calls?
    - Did I output the RED failure reason?
    - If my test had a compilation error, did I fix the test (not the implementation)?

    **Completeness:**
    - Did I fully implement everything in the spec?
    - Did I miss any requirements?
    - Are there edge cases I didn't handle?

    **Self-Correction:**
    - Did I run the mandatory self-correction checklist?
    - Did I fix any duplication, dead code, bad naming, magic numbers?
    - Did I flag file-size concerns?

    **Quality:**
    - Is this my best work?
    - Are names clear and accurate (match what things do, not how they work)?
    - Is the code clean and maintainable?

    If you find issues during self-review, fix them now before reporting.

    ## Report Format

    When done, report:
    - **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
    - TDD verification: Did you follow all TDD rules? Any violations?
    - What you implemented (or what you attempted, if blocked)
    - What you tested and test results
    - Files changed
    - Self-correction checklist results (what you found and fixed)
    - Any issues or concerns

    Use DONE_WITH_CONCERNS if you completed the work but have doubts about correctness.
    Use BLOCKED if you cannot complete the task. Use NEEDS_CONTEXT if you need
    information that wasn't provided. Never silently produce work you're unsure about.
```
```

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "feat(implementer-prompt): add TDD enforcement gate and mandatory self-correction

- Hard TDD requirement with explicit gate rules
- Mock-only assertion ban
- RED phase requires failure reason output
- Compilation error = reject test (not implementation)
- Mandatory self-correction checklist before reporting
- Updated report format with TDD verification section

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Update code-quality-reviewer-prompt.md — Linter Gate

**File:** `~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/subagent-driven-development/code-quality-reviewer-prompt.md`

**Changes:** Add linter gate, no-bypass suppression check, and dual-layer (auto-fix + gate) description.

- [ ] **Step 1: Replace the entire code-quality-reviewer-prompt.md content**

```markdown
# Code Quality Reviewer Prompt Template

Use this template when dispatching a code quality reviewer subagent.

**Purpose:** Verify implementation is well-built (clean, tested, maintainable) AND passes linter gate

**Only dispatch after spec compliance review passes.**

```
Task tool (superpowers:code-reviewer):
  Use template at requesting-code-review/code-reviewer.md

  WHAT_WAS_IMPLEMENTED: [from implementer's report]
  PLAN_OR_REQUIREMENTS: Task N from [plan-file]
  BASE_SHA: [commit before task]
  HEAD_SHA: [current commit]
  DESCRIPTION: [task summary]
```

## Linter Gate

Before starting code quality review, verify linter status:

### Step 1: Suppression Check (No-Bypass Rule)

Run this on the diff:
```bash
git diff BASE_SHA..HEAD_SHA | grep -iE '(eslint-disable|ts-ignore|noqa|pylint.*disable|pragma.*no.?cover|istanbul.*ignore|type:\s*ignore|//\s*pragma:\s*disable)'
```

**If any suppression is found:**
1. BLOCK the review — do not proceed to code quality assessment
2. Report: ❌ **BLOCKED: Suppression comment found in diff**
3. List the exact suppression(s) found with file:line
4. The implementer must remove the suppression and fix the underlying issue before re-review

The AI cannot decide a linter warning is acceptable. Human review is required for any suppression.

### Step 2: Auto-Fix Critical Errors

After suppression check passes, run linter on changed files:
```bash
# Python
ruff check --fix PATH_TO_CHANGED_FILES 2>&1 || true

# JavaScript/TypeScript
npx eslint --fix PATH_TO_CHANGED_FILES 2>&1 || true
```

**Auto-fix WITHOUT blocking:**
- Syntax/parse errors that prevent execution
- Security: hardcoded secrets, SQL injection candidates, path traversal, eval usage

**These are fixed silently. Do not block — fix and continue.**

### Step 3: Code Quality Review

After linter auto-fix, perform standard code quality review:

**The reviewer should check:**
- Does each file have one clear responsibility with a well-defined interface?
- Are units decomposed so they can be understood and tested independently?
- Is the implementation following the file structure from the plan?
- Did this implementation create new files that are already large, or significantly grow existing files?
- Are there remaining linter warnings (style, unused variables, complexity)?

**Code reviewer returns:** Strengths, Issues (Critical/Important/Minor), Assessment

## Critical Issues That Always Block

- Suppression comments found in diff (see Step 1)
- Security vulnerabilities (hardcoded secrets, injection risks)
- Syntax errors preventing compilation
- Any issue the reviewer marks as Critical

---

*In addition to standard code quality concerns, the reviewer should check:*
- Does each file have one clear responsibility with a well-defined interface?
- Are units decomposed so they can be understood and tested independently?
- Is the implementation following the file structure from the plan?
- Did this implementation create new files that are already large, or significantly grow existing files? (Don't flag pre-existing file sizes — focus on what this change contributed.)

**Code reviewer returns:** Strengths, Issues (Critical/Important/Minor), Assessment
```

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "feat(code-quality-reviewer): add linter gate with no-bypass suppression check

- Suppression grep blocks branch before quality review
- Auto-fix critical errors (syntax, security) silently
- Human review required for any suppression comment
- Dual-layer: auto-fix + gate pattern

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Smoke Test — Verify Skill Loads Correctly

**Files:** All three modified skill files

- [ ] **Step 1: Verify SKILL.md has valid frontmatter**

Run:
```bash
head -5 ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/subagent-driven-development/SKILL.md
```
Expected: YAML frontmatter with `name: subagent-driven-development` and `description: Use when executing...`

- [ ] **Step 2: Verify implementer-prompt.md is not empty**

Run:
```bash
wc -l ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/subagent-driven-development/implementer-prompt.md
```
Expected: > 50 lines (expanded from original ~35 lines)

- [ ] **Step 3: Verify code-quality-reviewer-prompt.md has linter gate**

Run:
```bash
grep -c "Suppression" ~/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/subagent-driven-development/code-quality-reviewer-prompt.md
```
Expected: > 0 (new suppression check section present)

- [ ] **Step 4: Commit smoke test verification**

```bash
git add -A && git commit -m "chore: add smoke test verification for skill files

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Self-Review Checklist

- [ ] Spec coverage: All spec requirements mapped to tasks?
  - TDD hard enforcement → Task 1, Step 1-2 ✅
  - Mock-only ban → Task 1 Step 2, Task 2 Step 1 ✅
  - RED failure reason → Task 1 Step 2, Task 2 Step 1 ✅
  - Compilation error = reject → Task 1 Step 2, Task 2 Step 1 ✅
  - No-bypass suppression rule → Task 1 Step 2, Task 3 Step 1 ✅
  - Dual-layer linter → Task 1 Step 3, Task 3 ✅
  - Mandatory self-correction → Task 1 Step 4, Task 2 Step 1 ✅
  - Breaking change notice → Task 1 Step 5 ✅
  - Updated diagrams → Task 1 Step 3 ✅
  - Updated advantages/red flags → Task 1 Step 7 ✅

- [ ] Placeholder scan: No "TBD", "TODO", "fill in later" in any step ✅
- [ ] Type consistency: All references to skill files use correct paths ✅
- [ ] No gaps: Every spec requirement has a corresponding task step ✅
