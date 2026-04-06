# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**VKE (Verified Knowledge Engine) v1** — a two-agent pipeline that ingests SEC filings and research papers, extracts atomic factual claims, verifies them against source documents using a local LLM, detects circular citations via recursive CTEs in DuckDB, and writes only verified claims to an Obsidian markdown wiki.

## Tech Stack

- **Language:** C# / .NET 8
- **Database:** DuckDB.NET (embedded, no DuckPGQ — all graph queries use recursive CTEs)
- **Local LLM:** LLM Studio at `http://localhost:1234/v1` (OpenAI-compatible API)
- **Testing:** xUnit + Moq
- **Wiki output:** Obsidian markdown vault

## Commands

```bash
# Build
dotnet build

# Run all tests
dotnet test

# Run a single test class
dotnet test --filter "FullyQualifiedName~CircularCitationTests"

# Run a single test method
dotnet test --filter "FullyQualifiedName~CircularCitationTests.DetectsCycle"

# CLI (once built)
vke ingest <url> --type sec_10k
vke query "What was Apple's revenue in FY2024?"
vke lint
vke graph <claim_id>
```

## Architecture

Two agents, one graph. The invariant: **only claims that pass verification mutate state.**

```
Raw Sources (SEC EDGAR, Semantic Scholar)
    → IngestAgent  (fetch → parse → extract citations → decompose into atomic claims)
    → VerifyAgent  (LLM fact-check → dedup/corroborate → store → detect cycles → write wiki)
    → DuckDB       (sources, claims, edges tables)
    → vault/wiki/  (only verified claims land here)
```

### Key architectural rules

- **Atomic Action Pair:** IngestAgent returns `(sourceId, List<Claim>)` — it never writes claims. VerifyAgent owns all writes to DuckDB and wiki. These two steps are inseparable.
- **Deterministic IDs:** `sources.id = sha256(url + published_at)`, `claims.id = sha256(normalized_statement + source_id)`. No auto-increment.
- **Trust ceiling:** A source's trust level is determined entirely by its `source_type` (Tier 1–4). No score formula — the type IS the trust level. See `source_types` lookup table.
- **Circular citation detection:** Uses recursive CTEs only (no DuckPGQ). Root source finder + cycle detector + independence scorer are all SQL.
- **Tier upgrade rule:** `EFFECTIVE_TIER = min(source_type.base_tier, 4 - floor(independent_source_count / 2))`. Cycle detected → forced Tier 4 (quarantine).

### File structure (target)

```
src/Vke.Core/
  Agents/          IngestAgent.cs, VerifyAgent.cs, LintAgent.cs
  Data/            VkeDbContext.cs, Models/{Source,Claim,Edge,SourceType}.cs
  Services/        LlmClient.cs, SecEdgarClient.cs, SemanticScholarClient.cs, WikiGenerator.cs
  Utils/           IdGenerator.cs, ClaimParser.cs, CitationExtractor.cs
tests/Vke.Core.Tests/
  Agents/          IngestAgentTests.cs, VerifyAgentTests.cs
  Data/            CircularCitationTests.cs, SourceTypeTests.cs
  Services/        LlmClientTests.cs
vault/
  raw/             Immutable originals — never modified after write
  wiki/            entities/, claims/, sources/, alerts/
```

### External APIs

- **SEC EDGAR:** `https://data.sec.gov/submissions/<CIK>.json` — no auth required
- **Semantic Scholar:** `https://api.semanticscholar.org/graph/v1/paper/<DOI>` — 100 req/s with API key
- **LLM Studio:** `http://localhost:1234/v1/chat/completions` — must be running locally

## Design docs

- Spec: `docs/superpowers/specs/2026-04-05-vke-design.md` — full schema, SQL queries, agent pseudocode, tier rules
- Plan: `docs/superpowers/plans/2026-04-05-vke-plan.md` — task-by-task build checklist (3 weeks)
