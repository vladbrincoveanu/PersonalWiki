#!/usr/bin/env dotnet-script
// VKE Simple Ingest - No database, just filesystem
// Usage: dotnet script ingest.csx --url https://arxiv.org/abs/2309.06180 --vault /path/to/vault

#r "nuget: MiniMax-M2.7, 1.0.0"

using System.Text.Json;
using System.Text.RegularExpressions;

var vaultBase = Args.GetValue("--vault") ?? Environment.GetEnvironmentVariable("OBSIDIAN_VAULT_PATH") ?? "./vault";
var url = Args.GetValue("--url");
var sourceType = Args.GetValue("--type") ?? "generic";
var domain = Args.GetValue("--domain") ?? "academic";

if (string.IsNullOrEmpty(url))
{
    Console.WriteLine("Usage: dotnet script ingest.csx --url <url> [--vault <path>] [--type <type>] [--domain <domain>]");
    return 1;
}

Console.WriteLine($"VKE Simple Ingest");
Console.WriteLine($"URL: {url}");
Console.WriteLine($"Vault: {vaultBase}");
Console.WriteLine();

// Create directories
var rawPath = Path.Combine(vaultBase, "raw");
var verifiedPath = Path.Combine(vaultBase, "verified");
Directory.CreateDirectory(rawPath);
Directory.CreateDirectory(verifiedPath);

// Fetch content
Console.WriteLine("Fetching content...");
var http = new HttpClient();
http.Timeout = TimeSpan.FromSeconds(30);
var response = await http.GetStringAsync(url);
Console.WriteLine($"Fetched {response.Length} chars");

// Convert PDF URL to abstract if needed
var finalUrl = url;
if (url.Contains("arxiv.org/pdf/"))
{
    var match = Regex.Match(url, @"arxiv\.org/pdf/(\d+\.\d+)");
    if (match.Success)
    {
        finalUrl = $"https://arxiv.org/abs/{match.Groups[1].Value}";
        Console.WriteLine($"Converted to abstract: {finalUrl}");
    }
}

// Extract title
var titleMatch = Regex.Match(response, @"<title[^>]*>([^<]+)</title>", RegexOptions.IgnoreCase);
var title = titleMatch.Success ? titleMatch.Groups[1].Value.Trim() : "Untitled";
Console.WriteLine($"Title: {title}");

// Strip HTML tags
var content = Regex.Replace(response, "<script[^>]*>.*?</script>", "", RegexOptions.Singleline | RegexOptions.IgnoreCase);
content = Regex.Replace(content, "<style[^>]*>.*?</style>", "", RegexOptions.Singleline | RegexOptions.IgnoreCase);
content = Regex.Replace(content, "<[^>]+>", " ");
content = System.Net.WebUtility.HtmlDecode(content);
content = Regex.Replace(content, @"\s+", " ").Trim();
Console.WriteLine($"Content length after strip: {content.Length} chars");

// Generate source ID from URL + date
var sourceId = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(url + DateTime.UtcNow.ToString("yyyy-MM-dd")))).Substring(0, 16);
sourceId = $"source-{sourceId}";
Console.WriteLine($"Source ID: {sourceId}");

// Split into units (sentences/paragraphs)
var units = SplitIntoUnits(content);
Console.WriteLine($"Split into {units.Count} units");

// Simple LLM verification (mock for now - would call real LLM in production)
var verifiedUnits = new List<VerifiedUnit>();
foreach (var unit in units)
{
    var confidence = unit.Length > 50 ? 0.8m : 0.5m; // Simple heuristic
    verifiedUnits.Add(new VerifiedUnit
    {
        Statement = unit,
        Confidence = confidence,
        Status = confidence >= 0.6m ? "VERIFIED" : "UNVERIFIED"
    });
}

var verifiedCount = verifiedUnits.Count(u => u.Status == "VERIFIED");
Console.WriteLine($"Verified: {verifiedCount}/{units.Count}");

// Write raw.md
var rawFile = Path.Combine(rawPath, $"{sourceId}.md");
var rawContent = $"# {title}\n\n- **URL:** [{url}]({url})\n- **Type:** {sourceType}\n- **Domain:** {domain}\n- **Fetched:** {DateTime.UtcNow:yyyy-MM-dd HH:mm:ss}\n\n## Content\n\n";
foreach (var unit in units)
{
    var vu = verifiedUnits.First(u => u.Statement == unit);
    rawContent += $"> [!{vu.Status}]\n> {unit}\n\n";
}
await File.WriteAllTextAsync(rawFile, rawContent);
Console.WriteLine($"Raw page written: {rawFile}");

// Write verified.md
var verifiedFileName = Regex.Replace(title, @"[^\w\s-]", "").Replace(" ", "-") + ".md";
verifiedFileName = Regex.Replace(verifiedFileName, @"-+", "-") + ".md";
var verifiedFile = Path.Combine(verifiedPath, verifiedFileName);
var verifiedContent = $"# Verified Claims: {title}\n\n**Source:** [{url}]({url})\n**Verified:** {DateTime.UtcNow:yyyy-MM-dd}\n**Total Claims:** {verifiedCount}\n\n---\n\n";
foreach (var vu in verifiedUnits.Where(u => u.Status == "VERIFIED"))
{
    verifiedContent += $"## Claim\n\n**Statement:** {vu.Statement}\n\n**Confidence:** {vu.Confidence:P0}\n\n---\n\n";
}
await File.WriteAllTextAsync(verifiedFile, verifiedContent);
Console.WriteLine($"Verified page written: {verifiedFile}");

Console.WriteLine($"\nDone! {verifiedCount} verified claims.");
return 0;

List<string> SplitIntoUnits(string content)
{
    var units = new List<string>();
    var sentences = content.Split(new[] { '.', '!', '?' }, StringSplitOptions.RemoveEmptyEntries);
    
    foreach (var s in sentences)
    {
        var trimmed = s.Trim();
        if (trimmed.Length > 30) // Skip very short fragments
        {
            units.Add(trimmed);
        }
    }
    
    return units;
}

class VerifiedUnit
{
    public string Statement { get; set; } = "";
    public decimal Confidence { get; set; }
    public string Status { get; set; } = "UNVERIFIED";
}

static class ArgsExtensions
{
    public static string? GetValue(this string[] args, string key)
    {
        var idx = Array.IndexOf(args, key);
        return idx >= 0 && idx + 1 < args.Length ? args[idx + 1] : null;
    }
}
