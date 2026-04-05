using Vke.Core.Agents;
using Vke.Core.Data;
using Vke.Core.Services;

var dbPath = args.Contains("--db") 
    ? args[Array.IndexOf(args, "--db") + 1] 
    : "vault/vke.duckdb";

Directory.CreateDirectory(Path.GetDirectoryName(dbPath)!);
var db = new VkeDbContext(dbPath);
db.InitializeDatabase();

var http = new HttpClient();
var llm = new LlmClient(http, "http://localhost:1234/v1");
var secEdgar = new SecEdgarClient(http);
var semScholar = new SemanticScholarClient(http);
var wikiGen = new WikiGenerator();

var command = args.FirstOrDefault() ?? "help";

switch (command)
{
    case "ingest":
        var url = args.GetValue("--url") ?? throw new ArgumentException("--url required");
        var sourceType = args.GetValue("--type") ?? "sec_10k";
        var domain = args.GetValue("--domain") ?? "financial";
        
        var ingestAgent = new IngestAgent(db, llm, secEdgar, semScholar);
        var (sourceId, claims) = await ingestAgent.IngestAsync(url, sourceType, domain);
        
        var verifyAgent = new VerifyAgent(db, llm);
        var result = await verifyAgent.VerifyAndStoreAsync(sourceId, claims);
        
        Console.WriteLine($"Ingested source {sourceId}");
        Console.WriteLine($"Verified: {result.Verified}, Quarantined: {result.Quarantined}, Cycles: {result.CyclesDetected}");
        break;
    
    case "lint":
        var lintAgent = new LintAgent(db);
        var report = lintAgent.GenerateReport();
        Console.WriteLine($"Stale claims: {report.StaleClaims.Count}");
        Console.WriteLine($"Orphan sources: {report.OrphanSources.Count}");
        Console.WriteLine($"Contradictions: {report.Contradictions.Count}");
        break;
    
    case "query":
        var queryText = args.GetValue("--q") ?? "";
        Console.WriteLine($"Query: {queryText}");
        break;
    
    case "help":
    default:
        Console.WriteLine("VKE CLI - Verified Knowledge Engine");
        Console.WriteLine("Commands:");
        Console.WriteLine("  vke ingest --url <url> --type <type> --domain <domain>");
        Console.WriteLine("  vke lint");
        Console.WriteLine("  vke query --q <text>");
        break;
}

static class ArgsExtensions
{
    public static string? GetValue(this string[] args, string key)
    {
        var idx = Array.IndexOf(args, key);
        return idx >= 0 && idx + 1 < args.Length ? args[idx + 1] : null;
    }
}
