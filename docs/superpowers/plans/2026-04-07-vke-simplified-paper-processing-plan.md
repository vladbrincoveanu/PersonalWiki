# Implementation Plan: VKE Simplified Paper Processing

## Overview
Simplify wiki output to 2 files per source: raw annotated + verified claims. Use Obsidian callouts.

## Tasks

### Task 1: Update Claim Model
**File:** `src/Vke.Core/Data/Models/Claim.cs`

Add `PrimarySourceUrl` property:
```csharp
public string? PrimarySourceUrl { get; set; }
```

---

### Task 2: Update VerifyAgent Thresholds
**File:** `src/Vke.Core/Agents/VerifyAgent.cs`

Change verification threshold from 0.5 to 0.6:
```csharp
const decimal VerificationThreshold = 0.6m;
```

Update verification logic:
- `>= 0.6` → Verified
- `< 0.6` → Mark for human review (use Unverifiable status)
- For claims with no external source → set score to 0.5, status = Unverified, needs human

---

### Task 3: Rewrite WikiGenerator - Raw Page
**File:** `src/Vke.Core/Services/WikiGenerator.cs`

Replace `GenerateSourcePage()` with new approach:

**New `GenerateRawPage()` method:**
- Write to `wiki/raw/{source-id}.md`
- Full content in paragraphs (NOT sentence-split)
- Add Obsidian callout blocks for each claim:
```markdown
> [!VERIFIED]
> Claim text here

> [!UNVERIFIED]
> This claim needs verification against primary source

> [!CANNOT_VERIFY]
> Experimental result - no primary source. Needs human review. Score: 50%
```
- Keep metadata in `.meta.json` file

---

### Task 4: Rewrite WikiGenerator - Verified Page
**File:** `src/Vke.Core/Services/WikiGenerator.cs`

**New `GenerateVerifiedPage()` method:**
- Write to `wiki/verified/{source-id}.md`
- Only claims with status = Verified AND score >= 0.6
- Each claim includes:
  - Statement
  - Confidence score
  - Source URLs found
  - Original source reference
```markdown
## Claim: [statement]

**Confidence:** 85%

**Sources:**
- https://source-url.com
- https://another-source.com

**Original:** https://original-paper-url.com
---
```

---

### Task 5: Remove Entity Page Generation
**File:** `src/Vke.Core/Services/WikiGenerator.cs`

Remove:
- `GenerateEntityPage()` method
- All entity-related logic from `WriteToWikiAsync`

---

### Task 6: Update VerifyAgent Flow
**File:** `src/Vke.Core/Agents/VerifyAgent.cs`

Update `WriteAnnotatedRawAsync()`:
- Call new `GenerateRawPage()` instead of current inline logic
- Pass all claims with their statuses for callout generation

Update `WriteToWikiAsync()`:
- Call new `GenerateVerifiedPage()` 
- Remove entity extraction/generation

---

### Task 7: Update Program.cs Paths
**File:** `src/Vke.Web/Program.cs`

Ensure wiki paths are correct:
```csharp
var rawPath = Path.Combine(vaultBase, "raw");
var verifiedPath = Path.Combine(vaultBase, "verified");
```

---

### Task 8: Update Tests
**Files:**
- `tests/Vke.Core.Tests/Services/WikiGeneratorTests.cs`
- `tests/Vke.Core.Tests/Agents/VerifyAgentTests.cs`

Update expected output format for new wiki structure.

---

## Files to Modify
1. `src/Vke.Core/Data/Models/Claim.cs` - Add PrimarySourceUrl
2. `src/Vke.Core/Services/WikiGenerator.cs` - Rewrite generation methods
3. `src/Vke.Core/Agents/VerifyAgent.cs` - Update thresholds and call new methods
4. `src/Vke.Web/Program.cs` - Update paths
5. Test files

## Files to Delete
- Entity page generation entirely

## Verification
After implementation:
1. Run `docker compose build vke`
2. Test ingest with arxiv paper
3. Check `wiki/raw/` and `wiki/verified/` directories
4. Verify Obsidian callout format
5. Verify only >60% claims in verified page
