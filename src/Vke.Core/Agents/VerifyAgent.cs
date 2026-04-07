using Vke.Core.Data;
using Vke.Core.Data.Models;
using Vke.Core.Services;
using Vke.Core.Utils;

namespace Vke.Core.Agents;

public class VerifyAgent
{
    private readonly VkeDbContext _db;
    private readonly ILlmClient _llm;
    private readonly WikiGenerator _wiki;
    private readonly WebSearchClient _webSearch;
    private readonly string _wikiPath;
    private const decimal VerificationThreshold = 0.6m;
    private const int MaxParallelVerifications = 5;

    public VerifyAgent(VkeDbContext db, ILlmClient llm, WikiGenerator? wiki = null, WebSearchClient? webSearch = null, string wikiPath = "vault/wiki")
    {
        _db = db;
        _llm = llm;
        _wiki = wiki ?? new WikiGenerator();
        _webSearch = webSearch ?? new WebSearchClient(new HttpClient(), Environment.GetEnvironmentVariable("BRAVE_SEARCH_API_KEY"));
        _wikiPath = wikiPath;
    }

    public async Task<VerifyResult> VerifyAndStoreAsync(string sourceId, List<Claim> claims)
    {
        var source = _db.GetSourceById(sourceId);
        if (source == null) throw new InvalidOperationException($"Source {sourceId} not found");

        Console.WriteLine($"[VerifyAgent] Starting verification for source {sourceId}");
        
        await WriteRawDumpAsync(source);
        
        var contentUnits = ContentSplitter.SplitBySentences(source.Content ?? "");
        Console.WriteLine($"[VerifyAgent] Split content into {contentUnits.Count} units");

        var verifiedUnits = await VerifyUnitsInParallelAsync(contentUnits, source);
        
        var allClaims = claims.ToList();
        foreach (var unit in verifiedUnits)
        {
            if (!string.IsNullOrEmpty(unit.Statement))
            {
                allClaims.Add(new Claim
                {
                    Statement = unit.Statement,
                    Status = unit.Status,
                    VerificationScore = unit.Confidence,
                    PrimarySourceUrl = unit.SourceUrl,
                    Normalized = unit.Statement.ToLowerInvariant().Trim()
                });
            }
        }

        await WriteAnnotatedRawAsync(source, allClaims, verifiedUnits);
        await WriteVerifiedPageAsync(source, verifiedUnits);

        var verified = allClaims.Where(c => c.Status == VerificationStatus.Verified && c.VerificationScore >= 0.6m).ToList();
        var unverifiable = allClaims.Where(c => c.Status == VerificationStatus.Unverifiable).ToList();

        return new VerifyResult
        {
            Verified = verified.Count,
            Corrected = 0,
            False = allClaims.Count - verified.Count - unverifiable.Count,
            Disputed = 0,
            Unverifiable = unverifiable.Count
        };
    }

    private async Task<List<VerifiedUnit>> VerifyUnitsInParallelAsync(List<string> units, Source source)
    {
        var results = new List<VerifiedUnit>();
        var semaphore = new SemaphoreSlim(MaxParallelVerifications);
        
        var tasks = units.Select(async unit =>
        {
            await semaphore.WaitAsync();
            try
            {
                return await VerifyUnitAsync(unit, source);
            }
            finally
            {
                semaphore.Release();
            }
        });

        var unitResults = await Task.WhenAll(tasks);
        return unitResults.Where(r => r != null).ToList()!;
    }

    private async Task<VerifiedUnit?> VerifyUnitAsync(string unit, Source source)
    {
        Console.WriteLine($"[VerifyAgent] Verifying unit: {unit.Substring(0, Math.Min(50, unit.Length))}...");
        
        var verifiedUnit = new VerifiedUnit { Statement = unit };

        var searchQuery = ExtractKeyFacts(unit);
        var searchResults = await _webSearch.SearchAsync(searchQuery);
        
        if (searchResults.Any(r => !string.IsNullOrEmpty(r.Url)))
        {
            var bestResult = searchResults.OrderByDescending(r => r.Confidence).First();
            verifiedUnit.SourceUrl = bestResult.Url;
            verifiedUnit.SourceTitle = bestResult.Title;
            verifiedUnit.SourceSnippet = bestResult.Snippet;
            
            var llmScore = await _llm.VerifyClaimAsync(unit, bestResult.Snippet + " " + source.Content);
            verifiedUnit.Confidence = (llmScore + bestResult.Confidence) / 2;
            
            if (verifiedUnit.Confidence >= 0.6m)
            {
                verifiedUnit.Status = VerificationStatus.Verified;
            }
            else if (verifiedUnit.Confidence >= 0.4m)
            {
                verifiedUnit.Status = VerificationStatus.Unverifiable;
            }
            else
            {
                verifiedUnit.Status = VerificationStatus.False;
            }
        }
        else
        {
            var sourceScore = await _llm.VerifyClaimAsync(unit, source.Content ?? source.Url);
            verifiedUnit.Confidence = sourceScore;
            verifiedUnit.Status = sourceScore >= 0.6m ? VerificationStatus.Verified : VerificationStatus.Unverifiable;
            verifiedUnit.SourceUrl = source.Url;
            verifiedUnit.SourceTitle = source.Title;
        }

        Console.WriteLine($"[VerifyAgent] Unit verified: confidence={verifiedUnit.Confidence:P0} status={verifiedUnit.Status}");
        return verifiedUnit;
    }

    private string ExtractKeyFacts(string text)
    {
        var important = text
            .Split(' ', StringSplitOptions.RemoveEmptyEntries)
            .Where(w => w.Length > 4 && !IsCommonWord(w))
            .Take(10)
            .ToArray();
        return string.Join(" ", important);
    }

    private bool IsCommonWord(string word)
    {
        var common = new[] { "that", "this", "with", "from", "have", "were", "been", "they", "their", "would", "could", "should", "about", "which", "there", "where", "when", "what", "who", "whom" };
        return common.Contains(word.ToLowerInvariant());
    }

    private async Task WriteRawDumpAsync(Source source)
    {
        var rawPath = Path.Combine(_wikiPath, "raw");
        Directory.CreateDirectory(rawPath);
        
        var filePath = Path.Combine(rawPath, $"{source.Id}.md");
        var sb = new System.Text.StringBuilder();
        
        sb.AppendLine($"# {source.Title ?? source.Id}");
        sb.AppendLine();
        sb.AppendLine($"- **URL:** [{source.Url}]({source.Url})");
        sb.AppendLine($"- **Type:** {source.SourceType}");
        sb.AppendLine($"- **Author:** {source.Author ?? "Unknown"}");
        sb.AppendLine($"- **Published:** {source.PublishedAt?.ToString() ?? "Unknown"}");
        sb.AppendLine($"- **Domain:** {source.Domain}");
        sb.AppendLine($"- **Fetched:** {source.FetchedAt:yyyy-MM-dd HH:mm:ss}");
        sb.AppendLine();
        sb.AppendLine("## Content");
        sb.AppendLine();
        sb.AppendLine(source.Content ?? "_No content available_");
        
        await File.WriteAllTextAsync(filePath, sb.ToString());
        Console.WriteLine($"[VerifyAgent] Raw dump written to {filePath}");
    }

    private async Task WriteAnnotatedRawAsync(Source source, List<Claim> claims, List<VerifiedUnit> verifiedUnits)
    {
        var rawPath = Path.Combine(_wikiPath, "raw");
        Directory.CreateDirectory(rawPath);
        
        var filePath = Path.Combine(rawPath, $"{source.Id}.md");
        var sb = new System.Text.StringBuilder();
        
        sb.AppendLine($"# {source.Title ?? source.Id}");
        sb.AppendLine();
        sb.AppendLine($"- **URL:** [{source.Url}]({source.Url})");
        sb.AppendLine($"- **Type:** {source.SourceType}");
        sb.AppendLine($"- **Author:** {source.Author ?? "Unknown"}");
        sb.AppendLine($"- **Published:** {source.PublishedAt?.ToString() ?? "Unknown"}");
        sb.AppendLine($"- **Domain:** {source.Domain}");
        sb.AppendLine($"- **Fetched:** {source.FetchedAt:yyyy-MM-dd HH:mm:ss}");
        sb.AppendLine();
        sb.AppendLine("## Content with Verification");
        sb.AppendLine();
        
        foreach (var unit in verifiedUnits)
        {
            var callout = GetCalloutForUnit(unit);
            sb.AppendLine(callout);
            sb.AppendLine();
        }
        
        await File.WriteAllTextAsync(filePath, sb.ToString());
        
        var metaPath = Path.Combine(rawPath, $"{source.Id}.meta.json");
        var meta = new
        {
            source.Id,
            source.Url,
            source.Title,
            source.SourceType,
            Author = source.Author,
            FetchedAt = source.FetchedAt,
            VerifiedAt = DateTime.UtcNow,
            TotalUnits = verifiedUnits.Count,
            VerifiedCount = verifiedUnits.Count(u => u.Status == VerificationStatus.Verified),
            UnverifiableCount = verifiedUnits.Count(u => u.Status == VerificationStatus.Unverifiable)
        };
        await File.WriteAllTextAsync(metaPath, System.Text.Json.JsonSerializer.Serialize(meta, new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
        
        Console.WriteLine($"[VerifyAgent] Annotated raw page written");
    }

    private async Task WriteVerifiedPageAsync(Source source, List<VerifiedUnit> verifiedUnits)
    {
        var verifiedPath = Path.Combine(_wikiPath, "verified");
        Directory.CreateDirectory(verifiedPath);
        
        var fileName = SanitizeFileName(source.Title ?? source.Id) + ".md";
        var filePath = Path.Combine(verifiedPath, fileName);
        
        var highConfidenceUnits = verifiedUnits.Where(u => u.Status == VerificationStatus.Verified && u.Confidence >= 0.6m).ToList();
        
        if (highConfidenceUnits.Count == 0)
        {
            Console.WriteLine("[VerifyAgent] No verified claims to write");
            return;
        }
        
        var sb = new System.Text.StringBuilder();
        sb.AppendLine($"# Verified Claims: {source.Title ?? source.Id}");
        sb.AppendLine();
        sb.AppendLine($"**Source:** [{source.Url}]({source.Url})");
        sb.AppendLine($"**Verified:** {DateTime.UtcNow:yyyy-MM-dd}");
        sb.AppendLine($"**Total Claims:** {highConfidenceUnits.Count}");
        sb.AppendLine();
        sb.AppendLine("---");
        sb.AppendLine();
        
        foreach (var unit in highConfidenceUnits)
        {
            sb.AppendLine($"## Claim");
            sb.AppendLine();
            sb.AppendLine($"**Statement:** {unit.Statement}");
            sb.AppendLine();
            sb.AppendLine($"**Confidence:** {unit.Confidence:P0}");
            sb.AppendLine();
            
            if (!string.IsNullOrEmpty(unit.SourceUrl))
            {
                sb.AppendLine("**Sources:**");
                sb.AppendLine($"- [{unit.SourceTitle ?? unit.SourceUrl}]({unit.SourceUrl})");
                sb.AppendLine();
            }
            
            if (!string.IsNullOrEmpty(unit.SourceSnippet))
            {
                sb.AppendLine("**Supporting Evidence:**");
                sb.AppendLine($"> {unit.SourceSnippet}");
                sb.AppendLine();
            }
            
            sb.AppendLine("---");
            sb.AppendLine();
        }
        
        await File.WriteAllTextAsync(filePath, sb.ToString());
        Console.WriteLine($"[VerifyAgent] Verified page written with {highConfidenceUnits.Count} claims");
    }

    private string GetCalloutForUnit(VerifiedUnit unit)
    {
        var (status, icon, color) = unit.Status switch
        {
            VerificationStatus.Verified when unit.Confidence >= 0.8m => ("VERIFIED", "✅", "green"),
            VerificationStatus.Verified when unit.Confidence >= 0.6m => ("LIKELY_TRUE", "⚠️", "yellow"),
            VerificationStatus.Unverifiable => ("UNVERIFIED", "❓", "yellow"),
            VerificationStatus.False => ("FALSE", "❌", "red"),
            _ => ("UNKNOWN", "⚪", "gray")
        };

        var sb = new System.Text.StringBuilder();
        sb.AppendLine($"> [!{status}]");
        sb.AppendLine($"> {icon} {unit.Statement}");
        sb.AppendLine($">");
        sb.AppendLine($"> _Confidence: {unit.Confidence:P0}_");
        
        if (!string.IsNullOrEmpty(unit.SourceUrl))
        {
            sb.AppendLine($">");
            sb.AppendLine($"> _Source: [{unit.SourceTitle ?? "link"}]({unit.SourceUrl})_");
        }
        
        return sb.ToString();
    }

    private string SanitizeFileName(string name)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var sanitized = new System.Text.StringBuilder();
        foreach (var c in name)
        {
            sanitized.Append(invalid.Contains(c) ? '_' : c);
        }
        return sanitized.ToString();
    }
}

public class VerifiedUnit
{
    public string Statement { get; set; } = "";
    public VerificationStatus Status { get; set; } = VerificationStatus.Unverified;
    public decimal Confidence { get; set; } = 0.5m;
    public string? SourceUrl { get; set; }
    public string? SourceTitle { get; set; }
    public string? SourceSnippet { get; set; }
}

public class VerifyResult
{
    public int Verified { get; set; }
    public int Corrected { get; set; }
    public int False { get; set; }
    public int Disputed { get; set; }
    public int Unverifiable { get; set; }
}
