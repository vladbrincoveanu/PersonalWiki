---
name: multi-agent-code-review
description: Use when reviewing any codebase - runs 6 parallel agents for code quality, library audit, simplification, performance, tests, and E2E checks
---

# Multi-Agent Code Review

## Overview
Dispatch 6-7 parallel agents to comprehensively review any codebase. Each agent focuses on one domain independently, running concurrently for speed.

## When to Use
- After major changes
- Before releases
- When encountering unexplained bugs
- During code review sessions
- "Extend tests", "audit deps", "check performance" requests

## Prerequisites
- [dispatching-parallel-agents] - MUST be loaded first for parallel execution
- Working directory set to project root

## Agent Types (Run All in Parallel)

| # | Agent | Purpose | Common Areas |
|---|-------|---------|---------------|
| 1 | **Code Review** | Fix high-severity bugs | Program.cs, Services, Clients |
| 2 | **Library Audit** | Check deps, security, deprecated | *.csproj files |
| 3 | **Simplification** | Reduce duplication, clean code | Agents, Utils, Helpers |
| 4 | **Performance** | Find bottlenecks | DB ops, async, I/O |
| 5 | **Tests & Coverage** | Verify tests pass | Test project |
| 6 | **E2E Tests** | Browser automation | E2E/Web tests |
| 7 | **Verification** | Final build/test validation | Full solution |

## Standard Agent Prompts

### 1. Code Review Agent
```
Fix HIGH severity code issues.

Common HIGH issues:
1. Silent exception swallowing - empty catch blocks
2. Return type mismatches - nullable returns vs non-nullable declarations
3. HttpClient per request - resource leak
4. Race conditions - File.Exists before file operations
5. Exception details leaked to clients

After fixes: dotnet build
```

### 2. Library Audit Agent
```
Audit NuGet dependencies.

Check:
- Deprecated packages (especially test frameworks like xunit v2)
- Version mismatches across projects
- Outdated Microsoft.* packages for current .NET version
- Known security vulnerabilities

After changes: dotnet restore && dotnet build
```

### 3. Simplification Agent
```
Simplify code - reduce duplication and clean structure.

Common targets:
- Duplicate methods that could call existing helpers
- String concatenation in loops (+=) → use StringBuilder
- Multiple .ToList() enumerations on same query
- Uncompiled Regex patterns
- Redundant checks (Any() after list just built)

Do NOT change logic - only simplify structure.
Verify: dotnet build
```

### 4. Performance Agent
```
Check for performance issues.

Focus areas:
- HttpClient usage (should use IHttpClientFactory)
- DB connections (leaks, not disposed)
- Async patterns (.Result/.Wait() deadlocks)
- Memory allocations (string concat in loops)
- Synchronous file I/O blocking threads

Return: Issues with file:line and severity (CRITICAL/HIGH/MEDIUM/LOW)
```

### 5. Tests & Coverage Agent
```
Run tests and analyze coverage.

Tasks:
1. Run: dotnet test
2. Check coverage data (coverlet.collector)
3. Identify low-coverage areas
4. List skipped tests

Return: passed/failed/skipped counts and coverage analysis.
```

### 6. E2E Tests Agent
```
Check E2E/browser test status.

Context:
- Web project with browser automation (Playwright/Selenium)
- E2E test project separate from unit tests

Check:
- Test framework installed
- BrowserTests logic matches actual API endpoints
- Hardcoded paths or environment dependencies
- Timeout issues (usually real API calls)

Return: E2E status and issues found.
```

### 7. Verification Agent (Run LAST)
```
After all agents complete, verify final state.

Tasks:
1. dotnet build 2>&1
2. dotnet test --no-build
3. Report final status

Return: Final build/test status.
```

## Common Issues by Severity

| Severity | Issue Type | Typical Files |
|----------|------------|---------------|
| CRITICAL | HttpClient per request | Program.cs, Startup |
| HIGH | Empty catch blocks | Clients, Services |
| HIGH | Return type mismatch | Utils, Helpers |
| MEDIUM | String += in loops | Generators, Builders |
| MEDIUM | Sync file I/O | File services |
| LOW | Uncached Regex | Parsers, Extractors |
| LOW | Version mismatches | *.csproj |

## Dispatch Template

```
Agent 1 → Code Review
Agent 2 → Library Audit  
Agent 3 → Simplification
Agent 4 → Performance
Agent 5 → Tests & Coverage
Agent 6 → E2E Tests
Agent 7 → Verification (after others)
```

## Customization

For C#/.NET projects, use `dotnet build` and `dotnet test`.
For other stacks, replace build/test commands with appropriate ones:
- Node: `npm build`, `npm test`
- Python: `python -m pytest`, `ruff check`
- Go: `go build`, `go test`

## Dependencies
- [dispatching-parallel-agents] - for parallel execution pattern
