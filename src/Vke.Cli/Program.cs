using Microsoft.Extensions.DependencyInjection;
using Vke.Core.Agents;
using Vke.Core.Data;
using Vke.Core.Services;

var services = new ServiceCollection();

var vaultBase = Environment.GetEnvironmentVariable("VKE_VAULT_BASE") 
    ?? "/openclaw/research";

var dbPath = args.Contains("--db") 
    ? args[Array.IndexOf(args, "--db") + 1] 
    : Path.Combine(vaultBase, "vke.duckdb");

Directory.CreateDirectory(Path.GetDirectoryName(dbPath)!);
using var db = new VkeDbContext(dbPath);
db.InitializeDatabase();

var apiKey = Environment.GetEnvironmentVariable("ANTHROPIC_AUTH_TOKEN") ?? "";
var baseUrl = Environment.GetEnvironmentVariable("ANTHROPIC_BASE_URL") ?? "https://api.minimax.io/anthropic";
var model = Environment.GetEnvironmentVariable("ANTHROPIC_MODEL") ?? "MiniMax-M2.7";

if (string.IsNullOrEmpty(apiKey))
{
    Console.WriteLine("Error: ANTHROPIC_AUTH_TOKEN environment variable not set.");
    Console.WriteLine("Run: export ANTHROPIC_AUTH_TOKEN=your-key && dotnet run --project src/Vke.Cli");
    return 1;
}

services.AddHttpClient("api", client =>
{
    client.Timeout = TimeSpan.FromMinutes(5);
    client.DefaultRequestHeaders.Add("x-api-key", apiKey);
    client.DefaultRequestHeaders.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", apiKey);
    client.DefaultRequestHeaders.Add("User-Agent", "VKE Research v1 (your@email.com)");
});

var serviceProvider = services.BuildServiceProvider();
var httpClientFactory = serviceProvider.GetRequiredService<IHttpClientFactory>();

var llm = new LlmClient(httpClientFactory.CreateClient("api"), baseUrl, model, apiKey);
var secEdgar = new SecEdgarClient(httpClientFactory.CreateClient("api"));
var semScholar = new SemanticScholarClient(httpClientFactory.CreateClient("api"));
var wikiGen = new WikiGenerator();
var fileScanner = new FileScanner();
var indexGen = new IndexGenerator();

var command = args.FirstOrDefault() ?? "help";

switch (command)
{
    case "ingest":
        var ticker = args.GetValue("--ticker");
        var url = args.GetValue("--url");
        
        if (!string.IsNullOrEmpty(ticker))
        {
            Console.WriteLine($"Looking up {ticker} filings...");
            var filings = await secEdgar.GetFilingsAsync(ticker.ToUpper(), "10-K");
            if (filings.Count == 0)
            {
                Console.WriteLine($"No 10-K filings found for {ticker}");
                return 1;
            }
            var latest = filings.OrderByDescending(f => f.FilingDate).First();
            url = latest.Url;
            Console.WriteLine($"Found {filings.Count} filings, using most recent: {latest.FilingDate} ({latest.Url.Split('/').Last()})");
        }
        
        if (string.IsNullOrEmpty(url))
        {
            Console.WriteLine("Error: --url or --ticker required");
            return 1;
        }
        
        var sourceType = args.GetValue("--type") ?? "sec_10k";
        var domain = args.GetValue("--domain") ?? "financial";
        
        Console.WriteLine($"Ingesting {sourceType} from {url}...");
        var ingestAgent = new IngestAgent(db, llm, secEdgar, semScholar, null);
        var (sourceId, claims) = await ingestAgent.IngestAsync(url, sourceType, domain);
        Console.WriteLine($"Extracted {claims.Count} claims, verifying with LLM...");
        
        var wikiPath = args.GetValue("--wiki") ?? Path.Combine(vaultBase, "wiki");
        var verifyAgent = new VerifyAgent(db, llm, wikiGen, null, wikiPath);
        var result = await verifyAgent.VerifyAndStoreAsync(sourceId, claims);
        
        Console.WriteLine($"Source ID: {sourceId}");
        Console.WriteLine($"Verified: {result.Verified}, Corrected: {result.Corrected}, False: {result.False}");
        Console.WriteLine($"Disputed: {result.Disputed}, Unverifiable: {result.Unverifiable}");
        Console.WriteLine($"Wiki written to: {wikiPath}/sources/ and {wikiPath}/entities/");
        
        Console.WriteLine("Scanning for new files...");
        await fileScanner.ScanAndIndexAsync(vaultBase, db);
        Console.WriteLine("Updating index...");
        await indexGen.GenerateIndexAsync(vaultBase, db);
        Console.WriteLine($"Index updated at {vaultBase}/index.md");
        break;
    
    case "lint":
        var lintAgent = new LintAgent(db);
        var lintReport = lintAgent.GenerateReport();
        Console.WriteLine($"Stale claims: {lintReport.StaleClaims.Count}");
        Console.WriteLine($"Orphan sources: {lintReport.OrphanSources.Count}");
        Console.WriteLine($"Contradictions: {lintReport.Contradictions.Count}");
        
        Console.WriteLine("Scanning for new files...");
        await fileScanner.ScanAndIndexAsync(vaultBase, db);
        Console.WriteLine("Updating index...");
        await indexGen.GenerateIndexAsync(vaultBase, db);
        break;
    
    case "correct":
    case "fix":
    {
        Console.WriteLine("Searching for correct values...");
        
        var correctDbPath = Path.Combine(vaultBase, "vke.duckdb");
        VkeDbContext correctDb;
        try
        {
            correctDb = new VkeDbContext(correctDbPath);
            correctDb.InitializeDatabase();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Error: Database not found or cannot be opened at {correctDbPath}. Run 'vke ingest' first. Details: {ex.Message}");
            return 1;
        }
        
        var yahooFinance = new YahooFinanceClient(httpClientFactory.CreateClient("api"));
        var correctionAgent = new CorrectionAgent(correctDb, yahooFinance);
        
        var correctResults = await correctionAgent.ProcessStaleAndFalseClaimsAsync();
        
        if (correctResults.Count == 0)
        {
            Console.WriteLine("No corrections needed.");
        }
        else
        {
            Console.WriteLine($"\nCorrected {correctResults.Count} claims:");
            foreach (var r in correctResults)
            {
                Console.WriteLine($"  - {r.ClaimId}");
                Console.WriteLine($"    Original: {r.OriginalValue}");
                Console.WriteLine($"    Corrected: {r.CorrectValue}");
                Console.WriteLine($"    Source: {r.Source}");
                Console.WriteLine();
            }
        }
        
        Console.WriteLine("Scanning for new files...");
        await fileScanner.ScanAndIndexAsync(vaultBase, correctDb);
        Console.WriteLine("Updating index...");
        await indexGen.GenerateIndexAsync(vaultBase, correctDb);
        break;
    }
    
    case "query":
        var queryText = args.GetValue("--q") ?? "";
        Console.WriteLine($"Query: {queryText}");
        Console.WriteLine("(Query not yet implemented - see v2)");
        break;
    
    case "help":
    default:
        Console.WriteLine("VKE CLI - Verified Knowledge Engine");
        Console.WriteLine("Usage:");
        Console.WriteLine("  export ANTHROPIC_AUTH_TOKEN=your-key");
        Console.WriteLine("  dotnet run --project src/Vke.Cli -- <command>");
        Console.WriteLine();
        Console.WriteLine("Commands:");
        Console.WriteLine("  ingest --ticker AAPL --type sec_10k --domain financial");
        Console.WriteLine("  ingest --url 'https://www.sec.gov/...' --type sec_10k --domain financial");
        Console.WriteLine("  Note: If both --ticker and --url provided, --ticker takes precedence");
        Console.WriteLine("  lint");
        Console.WriteLine("  query --q <text>");
        break;
}

return 0;

static class ArgsExtensions
{
    public static string? GetValue(this string[] args, string key)
    {
        var idx = Array.IndexOf(args, key);
        return idx >= 0 && idx + 1 < args.Length ? args[idx + 1] : null;
    }
}
