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
