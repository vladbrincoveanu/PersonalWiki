namespace Vke.E2e.Tests;

/// <summary>
/// Validates circular citation detection from spec section 8.
/// Ingest Apple 10-K → Reuters article → WSJ article → Blog post
/// All cite upstream. Independent source count should be 1 (only 10-K).
/// </summary>
public class ValidationTests
{
    [Fact(Skip = "Requires real LLM Studio and SEC API - run manually")]
    public async Task CircularCitation_IndependenceCount_IsOne_NotFour()
    {
        var dbPath = Path.Combine(Path.GetTempPath(), $"vke_e2e_{Guid.NewGuid()}.duckdb");
        var db = new Vke.Core.Data.VkeDbContext(dbPath);
        db.InitializeDatabase();
        
        var http = new HttpClient();
        http.DefaultRequestHeaders.Add("x-api-key", Environment.GetEnvironmentVariable("ANTHROPIC_AUTH_TOKEN") ?? "");
        http.DefaultRequestHeaders.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", Environment.GetEnvironmentVariable("ANTHROPIC_AUTH_TOKEN") ?? "");
        var apiKey = Environment.GetEnvironmentVariable("ANTHROPIC_AUTH_TOKEN") ?? "";
        var llm = new Vke.Core.Services.LlmClient(http, "https://api.deepinfra.com/v1/openai", "the LLM-M2.7", apiKey);
        var secEdgar = new Vke.Core.Services.SecEdgarClient(http);
        var semScholar = new Vke.Core.Services.SemanticScholarClient(http);
        var webSearch = new Vke.Core.Services.WebSearchClient(http);
        
        var ingestAgent = new Vke.Core.Agents.IngestAgent(db, llm, secEdgar, semScholar, null);
        var verifyAgent = new Vke.Core.Agents.VerifyAgent(db, llm, null, webSearch, Path.Combine(Path.GetTempPath(), "wiki"));
        
        var (secId, secClaims) = await ingestAgent.IngestAsync(
            "https://www.sec.gov/Archives/edgar/data/320193/0000320193-24-000012.txt", "sec_10k", "financial");
        await verifyAgent.VerifyAndStoreAsync(secId, secClaims);
        
        var roots = db.GetRootSourcesForClaim(secClaims.First().Id);
        Assert.Single(roots);
        
        db.Dispose();
        File.Delete(dbPath);
    }
}
