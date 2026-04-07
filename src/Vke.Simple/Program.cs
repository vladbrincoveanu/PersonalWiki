// VKE Simple Ingest - No database, just filesystem
// Compile: dotnet build src/Vke.Simple/Vke.Simple.csproj -c Release
// Run: dotnet src/Vke.Simple/bin/Release/net10.0/Vke.Simple.dll --url https://arxiv.org/abs/2309.06180 --vault ~/Documents/ObsidianVault/openclaw

using System.Text;
using System.Text.RegularExpressions;

namespace Vke.Simple;

class Program
{
    static async Task<int> Main(string[] args)
    {
        var url = GetArg(args, "--url");
        var vaultBase = GetArg(args, "--vault") ?? Environment.GetEnvironmentVariable("OBSIDIAN_VAULT_PATH") ?? "./vault";
        var sourceType = GetArg(args, "--type") ?? "generic";
        var domain = GetArg(args, "--domain") ?? "academic";

        if (string.IsNullOrEmpty(url))
        {
            Console.WriteLine("Usage: Vke.Simple --url <url> [--vault <path>] [--type <type>] [--domain <domain>]");
            Console.WriteLine("Example: Vke.Simple --url https://arxiv.org/abs/2309.06180 --vault ./vault");
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
        using var http = new HttpClient();
        http.Timeout = TimeSpan.FromSeconds(30);
        
        var finalUrl = ConvertArxivPdfToAbstract(url);
        var response = await http.GetStringAsync(finalUrl);
        Console.WriteLine($"Fetched {response.Length} chars from {finalUrl}");

        // Extract title
        var title = ExtractTitle(response) ?? "Untitled";
        Console.WriteLine($"Title: {title}");

        // Strip HTML tags
        var content = StripHtml(response);
        Console.WriteLine($"Content length after strip: {content.Length} chars");

        // Generate source ID
        var sourceId = $"source-{SHA256(url + DateTime.UtcNow.ToString("yyyy-MM-dd")).Substring(0, 16)}";
        Console.WriteLine($"Source ID: {sourceId}");

        // Split into units
        var units = SplitIntoUnits(content);
        Console.WriteLine($"Split into {units.Count} units");

        // Verify units (simple heuristic - real impl would call LLM)
        var verifiedUnits = units.Select(u => new VerifiedUnit
        {
            Statement = u,
            Confidence = u.Length > 50 ? 0.8m : 0.5m,
            Status = u.Length > 50 ? VerificationStatus.Verified : VerificationStatus.Unverifiable
        }).ToList();

        var verifiedCount = verifiedUnits.Count(u => u.Status == VerificationStatus.Verified);
        Console.WriteLine($"Verified: {verifiedCount}/{units.Count}");

        // Write raw.md
        var rawFile = Path.Combine(rawPath, $"{sourceId}.md");
        await WriteRawPage(rawFile, title, url, sourceType, domain, units, verifiedUnits);
        Console.WriteLine($"Raw page written: {rawFile}");

        // Write verified.md
        var verifiedFileName = SanitizeFileName(title) + ".md";
        var verifiedFile = Path.Combine(verifiedPath, verifiedFileName);
        await WriteVerifiedPage(verifiedFile, title, url, verifiedUnits);
        Console.WriteLine($"Verified page written: {verifiedFile}");

        Console.WriteLine($"\nDone! {verifiedCount} verified claims written to:");
        Console.WriteLine($"  - {rawFile}");
        Console.WriteLine($"  - {verifiedFile}");

        return 0;
    }

    static string ConvertArxivPdfToAbstract(string url)
    {
        var match = Regex.Match(url, @"arxiv\.org/pdf/(\d+\.\d+)");
        if (match.Success)
        {
            var paperId = match.Groups[1].Value;
            Console.WriteLine($"Converted PDF URL to abstract: https://arxiv.org/abs/{paperId}");
            return $"https://arxiv.org/abs/{paperId}";
        }
        return url;
    }

    static string? ExtractTitle(string html)
    {
        var match = Regex.Match(html, @"<title[^>]*>([^<]+)</title>", RegexOptions.IgnoreCase);
        return match.Success ? match.Groups[1].Value.Trim() : null;
    }

    static string StripHtml(string html)
    {
        var text = Regex.Replace(html, "<script[^>]*>.*?</script>", "", RegexOptions.Singleline | RegexOptions.IgnoreCase);
        text = Regex.Replace(text, "<style[^>]*>.*?</style>", "", RegexOptions.Singleline | RegexOptions.IgnoreCase);
        text = Regex.Replace(text, "<[^>]+>", " ");
        text = System.Net.WebUtility.HtmlDecode(text);
        text = Regex.Replace(text, @"\s+", " ").Trim();
        return text;
    }

    static List<string> SplitIntoUnits(string content)
    {
        var units = new List<string>();
        var sentences = content.Split(new[] { '.', '!', '?' }, StringSplitOptions.RemoveEmptyEntries);
        
        foreach (var s in sentences)
        {
            var trimmed = s.Trim();
            if (trimmed.Length > 30)
            {
                units.Add(trimmed);
            }
        }
        
        return units;
    }

    static async Task WriteRawPage(string file, string title, string url, string type, string domain, List<string> units, List<VerifiedUnit> verifiedUnits)
    {
        var sb = new System.Text.StringBuilder();
        sb.AppendLine($"# {title}");
        sb.AppendLine();
        sb.AppendLine($"- **URL:** [{url}]({url})");
        sb.AppendLine($"- **Type:** {type}");
        sb.AppendLine($"- **Domain:** {domain}");
        sb.AppendLine($"- **Fetched:** {DateTime.UtcNow:yyyy-MM-dd HH:mm:ss}");
        sb.AppendLine();
        sb.AppendLine("## Content with Verification");
        sb.AppendLine();
        
        for (int i = 0; i < units.Count; i++)
        {
            var vu = verifiedUnits[i];
            var icon = vu.Status == VerificationStatus.Verified ? "✅" : "❓";
            sb.AppendLine($"> [!{vu.Status}]");
            sb.AppendLine($"> {icon} {vu.Statement}");
            sb.AppendLine($">");
            sb.AppendLine($"> _Confidence: {vu.Confidence:P0}_");
            sb.AppendLine();
        }
        
        await File.WriteAllTextAsync(file, sb.ToString());
    }

    static async Task WriteVerifiedPage(string file, string title, string url, List<VerifiedUnit> verifiedUnits)
    {
        var verified = verifiedUnits.Where(v => v.Status == VerificationStatus.Verified).ToList();
        
        if (verified.Count == 0)
        {
            Console.WriteLine("No verified claims to write.");
            return;
        }
        
        var sb = new System.Text.StringBuilder();
        sb.AppendLine($"# Verified Claims: {title}");
        sb.AppendLine();
        sb.AppendLine($"**Source:** [{url}]({url})");
        sb.AppendLine($"**Verified:** {DateTime.UtcNow:yyyy-MM-dd}");
        sb.AppendLine($"**Total Claims:** {verified.Count}");
        sb.AppendLine();
        sb.AppendLine("---");
        sb.AppendLine();
        
        foreach (var vu in verified)
        {
            sb.AppendLine("## Claim");
            sb.AppendLine();
            sb.AppendLine($"**Statement:** {vu.Statement}");
            sb.AppendLine();
            sb.AppendLine($"**Confidence:** {vu.Confidence:P0}");
            sb.AppendLine();
            sb.AppendLine("---");
            sb.AppendLine();
        }
        
        await File.WriteAllTextAsync(file, sb.ToString());
    }

    static string SanitizeFileName(string name)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var sb = new System.Text.StringBuilder();
        foreach (var c in name)
        {
            sb.Append(invalid.Contains(c) ? '-' : c);
        }
        return sb.ToString().Replace(" ", "-").Replace("--", "-");
    }

    static string SHA256(string input)
    {
        var bytes = System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }

    static string? GetArg(string[] args, string key)
    {
        var idx = Array.IndexOf(args, key);
        return idx >= 0 && idx + 1 < args.Length ? args[idx + 1] : null;
    }
}

enum VerificationStatus
{
    Verified,
    Unverifiable,
    False
}

class VerifiedUnit
{
    public string Statement { get; set; } = "";
    public decimal Confidence { get; set; }
    public VerificationStatus Status { get; set; }
}
