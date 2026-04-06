# VKE v1 — Verified Knowledge Engine

## Build Plan: Financial Data + Research Papers

**Scope:** SEC filings (10-K, 10-Q, 8-K) + academic papers (arXiv, Semantic Scholar)
**Stack:** C# / .NET 8, DuckDB.NET, LLM Studio (MiniMax M2.7 or local GGUF via LLamaSharp), Obsidian wiki
**Hardware:** M4 MacBook Air 32GB (local LLM inference)
**Timeline:** 3 weeks to working prototype

---

## 1. Architecture: Two Agents, One Graph

```
                    ┌─────────────────────────────────────────────────┐
                    │                  RAW SOURCES                    │
                    │  SEC EDGAR API (HttpClient) · Semantic Scholar   │
                    └──────────────────┬──────────────────────────────┘
                                       │
                              ┌────────▼────────┐
                              │  INGEST AGENT    │
                              │                  │
                              │  1. Fetch source │
                              │  2. Extract meta │
                              │  3. Decompose    │
                              │     into atomic  │
                              │     claims       │
                              │  4. Extract what │
                              │     source CITES │
                              └────────┬─────────┘
                                       │
                              ┌────────▼─────────┐
                              │  VERIFY AGENT     │
                              │                   │
                              │  1. LLM Studio    │
                              │     (fact check   │
                              │      vs source)   │
                              │  2. Independence  │
                              │     check via     │
                              │     citation      │
                              │     graph         │
                              │  3. PASS → store  │
                              │     FAIL → quarantine
                              └────────┬──────────┘
                                       │
                    ┌──────────────────▼───────────────────────────┐
                    │              DuckDB.NET                       │
                    │  sources · claims · edges · property graph    │
                    └──────────────────┬───────────────────────────┘
                                       │
                    ┌──────────────────▼───────────────────────────┐
                    │           OBSIDIAN WIKI (wiki/)                │
                    │  Only verified claims get written here         │
                    │  Structured MD: entities/ claims/ sources/    │
                    └──────────────────────────────────────────────┘
```

**The rule:** Only claims that pass verification mutate state. Everything else stays in `raw/`. This is the Atomic Action Pair — generate + verify as one inseparable transaction.

**Note on DuckDB.NET:** DuckPGQ extension (property graph) is not available in DuckDB.NET. All circular citation detection uses recursive CTEs in plain SQL — this achieves the same result without the property graph API.

---

## 2. DuckDB Schema

Three core tables. No authors table yet (author is a field on sources). No agent_log yet (add in week 3 with lint).

```sql
-- Source type determines base tier. No formula, no weights.
-- A source IS its type. The type IS the trust level.

CREATE TABLE sources (
    id              TEXT PRIMARY KEY,           -- deterministic hash: sha256(url + published_at)
    url             TEXT NOT NULL,
    title           TEXT,
    source_type     TEXT NOT NULL,              -- FK to source_types lookup
    author          TEXT,
    publication     TEXT,
    published_at    DATE,
    fetched_at      TIMESTAMP DEFAULT now(),
    domain          TEXT,                       -- 'financial' | 'academic' | 'news' | 'other'
    
    -- What does THIS source cite? Extracted during ingestion.
    cites_urls      TEXT[],                     -- raw URLs found in the document
    cites_source_ids TEXT[]                     -- resolved to source IDs post-ingestion
);

CREATE TABLE claims (
    id              TEXT PRIMARY KEY,           -- sha256(normalized_statement + source_id)
    statement       TEXT NOT NULL,              -- atomic factual claim, one sentence
    normalized      TEXT NOT NULL,              -- lowercase, entity-resolved version for dedup
    source_id       TEXT NOT NULL REFERENCES sources(id),
    location        TEXT,                       -- section/page/paragraph in source document
    domain          TEXT,                       -- 'financial' | 'academic'
    
    -- Verification state
    verified        BOOLEAN DEFAULT FALSE,      -- passed LLM verification
    verification_score REAL,                    -- LLM confidence (0.0 to 1.0)
    
    -- Tier comes from source_type lookup, not from a formula
    tier            INTEGER DEFAULT 4,          -- 1-4, set by source_type on insert
    
    -- Independence metadata (computed by graph query)
    independent_source_count INTEGER DEFAULT 0, -- how many truly independent sources assert this
    
    -- Lifecycle
    first_seen      TIMESTAMP DEFAULT now(),
    last_verified   TIMESTAMP,
    stale_after     TIMESTAMP,                  -- domain-dependent: 90 days for financials, 1 year for academic
    is_active       BOOLEAN DEFAULT TRUE        -- FALSE = quarantined or superseded
);

CREATE TABLE edges (
    source_node     TEXT NOT NULL,              -- source_id, claim_id, or author name
    target_node     TEXT NOT NULL,
    relation        TEXT NOT NULL,              -- see relation types below
    weight          REAL DEFAULT 1.0,
    created_at      TIMESTAMP DEFAULT now(),
    
    -- Provenance: which agent created this, from which source
    created_by      TEXT,                       -- 'ingest_agent' | 'verify_agent' | 'lint_agent'
    evidence_source TEXT,                       -- source_id where this relationship was found
    
    PRIMARY KEY (source_node, target_node, relation)
);

-- Relation types:
--   'source_cites_source'     → Source A cites Source B (extracted from references/bibliography)
--   'source_asserts_claim'    → Source A makes Claim X
--   'claim_corroborates'      → Claim X and Claim Y say the same thing from independent sources
--   'claim_contradicts'       → Claim X and Claim Y conflict
--   'claim_derived_from'      → Claim X was inferred from Claim Y (inference chain tracking)
```

### Source Type Lookup Table

No formula. A source IS its type. The type determines the ceiling.

```sql
CREATE TABLE source_types (
    type_key        TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    base_tier       INTEGER NOT NULL,           -- tier assigned on ingestion
    max_confidence  REAL NOT NULL,              -- ceiling for claims from this source type alone
    description     TEXT,
    examples        TEXT
);

INSERT INTO source_types VALUES
-- TIER 1: Primary sources with legal/institutional backing
('sec_10k',         'SEC 10-K Annual Report',       1, 0.95, 'Audited financials, legally liable',           'Apple 10-K FY2025'),
('sec_10q',         'SEC 10-Q Quarterly Report',     1, 0.90, 'Reviewed (not audited) quarterly financials',  'MSFT 10-Q Q3 2025'),
('sec_8k',          'SEC 8-K Current Report',        1, 0.92, 'Material event disclosure, legally liable',    'NVDA 8-K CEO change'),
('sec_proxy',       'SEC Proxy Statement (DEF 14A)', 1, 0.90, 'Compensation, governance, votes',             'AMZN DEF 14A'),
('peer_reviewed',   'Peer-Reviewed Journal Paper',   1, 0.88, 'Peer review process, reproducibility norms',  'Nature, Science, JAMA'),
('central_bank',    'Central Bank Publication',       1, 0.93, 'Fed minutes, ECB reports, BIS papers',        'FOMC minutes'),

-- TIER 2: Credible secondary sources
('preprint',        'arXiv/SSRN Preprint',           2, 0.70, 'Not peer-reviewed but author-identified',     'arXiv:2508.17906'),
('news_wire',       'Wire Service Report',            2, 0.75, 'Reuters, AP, Bloomberg — editorial standards','Reuters earnings report'),
('sell_side',       'Sell-Side Analyst Report',       2, 0.65, 'Conflicts of interest but domain expertise',  'Goldman Sachs initiation'),
('data_provider',   'Financial Data Provider',        2, 0.80, 'Bloomberg, S&P, Refinitiv — aggregated data', 'Bloomberg Terminal data'),
('govt_stats',      'Government Statistical Agency',  2, 0.85, 'BLS, Census, Eurostat',                      'CPI release'),

-- TIER 3: Useful but unverified
('news_article',    'News Article / Journalism',      3, 0.55, 'Editorial but not primary',                   'WSJ feature, FT analysis'),
('conference_talk', 'Conference Talk / Transcript',   3, 0.55, 'Expert opinion, not peer-reviewed',           'NeurIPS keynote'),
('company_blog',    'Company Blog / PR',              3, 0.50, 'Self-reported, marketing incentive',          'Stripe engineering blog'),
('industry_report', 'Industry / Consulting Report',   3, 0.55, 'McKinsey, Gartner — often paywalled',        'Gartner Magic Quadrant'),

-- TIER 4: Unverified / opinion
('blog_post',       'Personal Blog / Substack',       4, 0.30, 'No editorial oversight',                     'Random Medium post'),
('social_media',    'Social Media Post',              4, 0.20, 'No verification, viral incentive',            'Twitter thread'),
('anonymous',       'Anonymous / Unknown Origin',     4, 0.10, 'Cannot verify author or source',              'Pastebin, anon forum'),
('llm_generated',   'LLM-Generated Content',          4, 0.15, 'Circular risk — LLM verifying LLM output',   'ChatGPT summary');
```

---

## 3. Circular Citation Detection

This is the core novel piece. Uses recursive CTEs — no DuckPGQ needed.

### The Algorithm

**Step 1: Build the citation subgraph for a claim.**

```sql
-- For claim 'claim_xyz', get all asserting sources and their citation relationships
WITH asserting_sources AS (
    SELECT source_node AS source_id
    FROM edges
    WHERE target_node = 'claim_xyz'
    AND relation = 'source_asserts_claim'
),
citation_subgraph AS (
    SELECT e.source_node AS citing, e.target_node AS cited
    FROM edges e
    WHERE e.relation = 'source_cites_source'
    AND e.source_node IN (SELECT source_id FROM asserting_sources)
    AND e.target_node IN (SELECT source_id FROM asserting_sources)
)
SELECT * FROM citation_subgraph;
```

**Step 2: Find root sources (no inbound citation from other asserting sources).**

```sql
-- Root sources: assert the claim but no other asserting source cites them
WITH asserting_sources AS (
    SELECT source_node AS source_id
    FROM edges
    WHERE target_node = :claim_id
    AND relation = 'source_asserts_claim'
),
cited_by_peers AS (
    SELECT DISTINCT e.target_node AS source_id
    FROM edges e
    WHERE e.relation = 'source_cites_source'
    AND e.source_node IN (SELECT source_id FROM asserting_sources)
    AND e.target_node IN (SELECT source_id FROM asserting_sources)
)
SELECT a.source_id AS root_source,
       s.title,
       s.source_type,
       st.base_tier
FROM asserting_sources a
JOIN sources s ON a.source_id = s.id
JOIN source_types st ON s.source_type = st.type_key
WHERE a.source_id NOT IN (SELECT source_id FROM cited_by_peers);

-- The COUNT of this result = true independent source count for the claim
```

**Step 3: Detect actual cycles (source A cites B cites C cites A).**

```sql
-- Detect cycles in the citation graph using recursive CTE
WITH RECURSIVE citation_chain AS (
    SELECT 
        source_node AS start_node,
        target_node AS current_node,
        [source_node] AS path,
        1 AS depth,
        FALSE AS is_cycle
    FROM edges
    WHERE relation = 'source_cites_source'
    
    UNION ALL
    
    SELECT
        cc.start_node,
        e.target_node AS current_node,
        list_append(cc.path, e.target_node) AS path,
        cc.depth + 1,
        e.target_node = cc.start_node AS is_cycle
    FROM citation_chain cc
    JOIN edges e ON cc.current_node = e.source_node
    WHERE e.relation = 'source_cites_source'
    AND cc.depth < 10
    AND cc.is_cycle = FALSE
    AND list_contains(cc.path, e.target_node) = FALSE
)
SELECT DISTINCT start_node, path, depth
FROM citation_chain
WHERE is_cycle = TRUE
ORDER BY depth;
```

### The Tier Upgrade Rule

```
EFFECTIVE_TIER = min(
    source_type.base_tier,                    -- ceiling from source type
    4 - floor(independent_source_count / 2)   -- bonus from independence (capped)
)

In practice:
- 1 independent source  → tier stays at source_type base
- 2 independent sources → tier improves by 1 (if not already 1)
- 4+ independent sources → tier 1 (gold) regardless of source type
- 0 independent sources → shouldn't happen (the source itself counts)
- Cycle detected        → tier forced to 4 (quarantine) until resolved
```

---

## 4. Ingest Agent — What It Actually Does

```csharp
// The ingest pipeline for one source document

public class IngestAgent
{
    private readonly HttpClient _http;
    private readonly IDbConnection _db;
    private readonly LlmClient _llm;

    public async Task<(string sourceId, List<Claim> claims)> IngestAsync(string url, string sourceType, string domain)
    {
        // 1. FETCH
        var rawContent = await FetchAsync(url, sourceType);
        var rawPath = SaveToRaw(rawContent, url);
        
        // 2. REGISTER SOURCE
        var sourceId = GenerateSourceId(url, rawContent.PublishedAt);
        var source = new Source
        {
            Id = sourceId,
            Url = url,
            Title = rawContent.Title,
            SourceType = sourceType,
            Author = rawContent.Author,
            Domain = domain,
            CitesUrls = ExtractCitations(rawContent),
        };
        await InsertSourceAsync(source);
        
        // 3. RESOLVE CITATIONS
        foreach (var citedUrl in source.CitesUrls)
        {
            var existingId = await ResolveCitationAsync(citedUrl);
            if (existingId != null)
            {
                await InsertEdgeAsync(new Edge
                {
                    SourceNode = sourceId,
                    TargetNode = existingId,
                    Relation = "source_cites_source",
                    CreatedBy = "ingest_agent",
                });
            }
        }
        
        // 4. DECOMPOSE INTO ATOMIC CLAIMS (Claimify-style via LLM)
        var claims = await DecomposeClaimsAsync(rawContent.Content, sourceId);
        
        return (sourceId, claims);
    }
}
```

### Claim Decomposition Prompt (LLM Studio)

```
You are a factual claim extractor. Extract all verifiable claims from this document.

Rules:
- One claim per line
- Each claim must be a complete, self-contained sentence
- Resolve all pronouns ("it" → company name, "the study" → paper title)
- Resolve relative dates ("last quarter" → "Q3 2025")
- Split compound claims ("Revenue was $X and grew Y%" → two claims)
- Skip opinions, predictions, forward-looking statements
- Skip boilerplate, transitions, formatting
- For financial claims: always include the entity name, metric, value, and time period
- For research claims: always include what was measured, the result, and the dataset/conditions

Output format (one per line):
CLAIM: [the atomic claim]
LOCATION: [section or page where found]
```

---

## 5. Verify Agent — Atomic Action Pair

```csharp
public class VerifyAgent
{
    private readonly IDbConnection _db;
    private readonly LlmClient _llm;

    public async Task<VerifyResult> VerifyAndStoreAsync(string sourceId, List<Claim> claims)
    {
        var source = await GetSourceAsync(sourceId);
        var baseTier = await GetBaseTierAsync(source.SourceType);
        
        var verifiedClaims = new List<string>();
        var quarantinedClaims = new List<Claim>();
        
        foreach (var claim in claims)
        {
            // STEP 1: Grounded fact check via LLM Studio
            var score = await _llm.VerifyClaimAsync(claim.Statement, source);
            
            if (score < 0.5m)
            {
                quarantinedClaims.Add(claim);
                continue;
            }
            
            // STEP 2: Dedup
            var existing = await FindExistingClaimAsync(claim.Normalized);
            if (existing != null)
            {
                await AddCorroborationEdgeAsync(sourceId, existing.Id);
                await UpdateIndependenceScoresAsync(existing.Id);
                continue;
            }
            
            // STEP 3: Store new verified claim
            var claimId = GenerateClaimId(claim.Normalized, sourceId);
            await InsertClaimAsync(new Claim
            {
                Id = claimId,
                Statement = claim.Statement,
                Normalized = claim.Normalized,
                SourceId = sourceId,
                Location = claim.Location,
                Domain = source.Domain,
                Verified = true,
                VerificationScore = score,
                Tier = baseTier,
                IndependentSourceCount = 1,
                StaleAfter = ComputeStaleDate(source.Domain),
            });
            
            await InsertEdgeAsync(new Edge
            {
                SourceNode = sourceId,
                TargetNode = claimId,
                Relation = "source_asserts_claim",
                CreatedBy = "verify_agent",
            });
            
            verifiedClaims.Add(claimId);
        }
        
        // STEP 4: Check for cycles
        var cycles = await DetectCyclesAsync(sourceId);
        if (cycles.Any())
            await QuarantineCyclicClaimsAsync(cycles);
        
        // STEP 5: Write verified claims to wiki
        await WriteToWikiAsync(sourceId, verifiedClaims);
        
        return new VerifyResult
        {
            Verified = verifiedClaims.Count,
            Quarantined = quarantinedClaims.Count,
            CyclesDetected = cycles.Count,
        };
    }
}
```

### LLM Studio Integration

LLM Studio exposes an OpenAI-compatible API. Call it via HttpClient:

```csharp
public class LlmClient
{
    private readonly HttpClient _http;
    private readonly string _baseUrl; // e.g., "http://localhost:1234/v1"
    
    public async Task<decimal> VerifyClaimAsync(string claim, Source sourceDocument)
    {
        var prompt = $@"Verify this claim against the source document.

CLAIM: {claim}

SOURCE DOCUMENT:
{sourceDocument.Content}

Respond with a single number between 0.0 and 1.0 representing how well the claim is supported by the source.
0.0 = completely unsupported or contradicts the source
1.0 = fully supported by the source

Only output the number.";
        
        var response = await _http.PostAsJsonAsync($"{_baseUrl}/chat/completions", new
        {
            model = "local",
            messages = new[] { new { role = "user", content = prompt } },
            temperature = 0.1m,
        });
        
        var result = await response.Content.ReadFromJsonAsync<LlmResponse>();
        return decimal.Parse(result.Choices[0].Message.Content.Trim());
    }
}
```

---

## 6. Wiki Output Structure

```
vault/
├── raw/                          # immutable originals, never modified
│   ├── sec/
│   │   ├── AAPL-10K-2025.md
│   │   └── NVDA-8K-2025-03.md
│   └── papers/
│       └── 2508.17906.md
│
├── wiki/                         # ONLY verified claims land here
│   ├── entities/
│   │   ├── apple-inc.md
│   │   └── nvidia-corp.md
│   ├── claims/
│   │   ├── aapl-revenue-fy2024.md
│   │   └── nvda-datacenter-q3.md
│   ├── sources/
│   │   ├── aapl-10k-2025.md
│   │   └── arxiv-2508-17906.md
│   └── alerts/
│       ├── contradictions.md
│       └── cycles.md
│
├── index.md
├── schema.md
└── vke.duckdb
```

---

## 7. Build Plan — 3 Weeks

### Week 1: Foundation + Ingest Agent

**Day 1-2: Project setup + DuckDB**
- [ ] Create .NET 8 solution: `Vke.sln`, `src/Vke.Core/`, `tests/Vke.Core.Tests/`
- [ ] Add DuckDB.NET package, create `VkeDbContext` with all tables
- [ ] Insert source_types lookup data
- [ ] Write test: insert source → query graph → verify structure

**Day 3-4: Ingest Agent for SEC filings**
- [ ] Wire SEC EDGAR API via HttpClient (company tickers → filing access)
- [ ] Write content parser for 10-K, 10-Q, 8-K (extract text from HTML)
- [ ] Write citation extractor (parse references section)
- [ ] Write Claimify claim decomposer (LLM Studio prompt + parser)
- [ ] Test: ingest Apple 10-K FY2024 → verify claims in DuckDB

**Day 5: Ingest Agent for research papers**
- [ ] Wire Semantic Scholar API for paper fetch + citation graph
- [ ] Adapt claim decomposer for abstract/conclusion extraction
- [ ] Test: ingest a finance paper → verify claims + citations

### Week 2: Verify Agent + Circular Citation Detection

**Day 1-2: LLM Studio integration**
- [ ] Wire LLM Studio OpenAI-compatible API client
- [ ] Write verification prompt (fact check grounded in source document)
- [ ] Set threshold (0.5 for now)
- [ ] Wire into pipeline: Ingest → Verify → Store/Quarantine

**Day 3-4: Circular citation detection (SQL/CTE approach)**
- [ ] Implement root source finder (recursive CTE)
- [ ] Implement cycle detector (recursive CTE)
- [ ] Write independence score updater
- [ ] Write tier upgrade rule
- [ ] Test: create circular chain → verify detection
- [ ] Test: 3 news articles citing Reuters → verify independence count = 1

**Day 5: Wiki generator**
- [ ] Write entity page generator
- [ ] Write source page generator
- [ ] Write index.md auto-updater
- [ ] Generate alerts/cycles.md and alerts/contradictions.md

### Week 3: Lint + Integration + First Real Test

**Day 1-2: Lint agent**
- [ ] Stale claim scanner
- [ ] Orphan detector
- [ ] Contradiction finder
- [ ] Generate lint_report.md

**Day 3-4: End-to-end test**
- [ ] Ingest 5 SEC filings (AAPL, MSFT, NVDA, GOOGL, AMZN latest 10-K)
- [ ] Ingest 5 research papers
- [ ] Ingest 10 news articles referencing those filings
- [ ] Run full pipeline → validate independence scores, tiers, cycles

**Day 5: CLI + polish**
- [ ] CLI: `vke ingest <url> --type sec_10k`
- [ ] CLI: `vke query "What was Apple's revenue in FY2024?"`
- [ ] CLI: `vke lint`
- [ ] CLI: `vke graph <claim_id>`
- [ ] README

---

## 8. First Validation Test

After Week 3:

1. Ingest Apple 10-K FY2024 (primary source, Tier 1)
2. Ingest a Reuters article reporting Apple's FY2024 revenue (cites the 10-K)
3. Ingest a WSJ article reporting the same revenue (cites Reuters)
4. Ingest a blog post reporting the same revenue (cites WSJ)

**Expected:** Claim "Apple's revenue was $394.3B in FY2024" has independent_source_count = **1** (root source = 10-K). No cycles.

Then ingest Bloomberg data for same figure:
**Expected:** independent_source_count = **2**.

---

## 9. What We're NOT Building Yet (v2)

- Author Verification Agent
- Corroboration Agent
- Synthesis Agent
- Embedding-based search
- Web UI (Obsidian IS the UI)

---

## 10. Dependencies

```xml
<!-- .NET 8 -->
<PackageReference Include="DuckDB.NET" Version="*" />
<PackageReference Include="Microsoft.Extensions.Http" Version="8.*" />
```

```bash
# LLM Studio (run separately)
# Connect to http://localhost:1234/v1 (OpenAI-compatible)
```

### SEC EDGAR API

Free, no auth needed: `https://data.sec.gov/submissions/<CIK>.json`
Filings: `https://www.sec.gov/Archives/edgar/data/<CIK>/<accession>/<doc>.html`

### Semantic Scholar API

Free API: `https://api.semanticscholar.org/graph/v1/paper/<DOI>?fields=authors,title,abstract,references,citations`
Rate limit: 100 requests/second with API key.
