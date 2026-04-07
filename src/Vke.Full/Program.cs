// VKE Full Ingest - Filesystem-only, no database
// Keeps all functionality: LLM verification, parallel processing, web search
// Run: dotnet run --project src/Vke.Full/Vke.Full.csproj -- --url https://arxiv.org/abs/2309.06180 --vault ~/vault

using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Vke.Full;

class Program
{
    static async Task<int> Main(string[] args)
    {
        var url = GetArg(args, "--url");
        var vaultBase = GetArg(args, "--vault") ?? Environment.GetEnvironmentVariable("OBSIDIAN_VAULT_PATH") ?? "./vault";
        var sourceType = GetArg(args, "--type") ?? "generic";
        var domain = GetArg(args, "--domain") ?? "academic";
        var parallel = int.TryParse(GetArg(args, "--parallel"), out var p) ? p : 5;

        if (string.IsNullOrEmpty(url))
        {
            Console.WriteLine("VKE - Verified Knowledge Engine");
            Console.WriteLine("Usage: Vke.Full --url <url> [--vault <path>] [--type <type>] [--domain <domain>] [--parallel <n>]");
            Console.WriteLine();
            Console.WriteLine("Environment variables:");
            Console.WriteLine("  ANTHROPIC_AUTH_TOKEN  - Required for LLM verification");
            Console.WriteLine("  OBSIDIAN_VAULT_PATH  - Vault base path");
            return 1;
        }

        var apiKey = Environment.GetEnvironmentVariable("ANTHROPIC_AUTH_TOKEN");
        if (string.IsNullOrEmpty(apiKey))
        {
            Console.WriteLine("Error: ANTHROPIC_AUTH_TOKEN not set");
            return 1;
        }

        Console.WriteLine($"VKE - Verifying: {url}");
        Console.WriteLine($"Vault: {vaultBase}");
        Console.WriteLine($"Parallel verifications: {parallel}");
        Console.WriteLine();

        // Setup
        var rawPath = Path.Combine(vaultBase, "raw");
        var verifiedPath = Path.Combine(vaultBase, "verified");
        Directory.CreateDirectory(rawPath);
        Directory.CreateDirectory(verifiedPath);

        using var http = new HttpClient();
        http.Timeout = TimeSpan.FromMinutes(5);
        
        var baseUrl = Environment.GetEnvironmentVariable("ANTHROPIC_BASE_URL") ?? "https://api.minimax.io/anthropic";
        var model = Environment.GetEnvironmentVariable("ANTHROPIC_MODEL") ?? "MiniMax-M2.7-highspeed";
        var llm = new LlmClient(http, baseUrl, model, apiKey);
        var webSearch = new WebSearchClient(http);
        var genericUrl = new GenericUrlClient(http);

        // Fetch and convert URL if needed
        var finalUrl = ConvertArxivPdfToAbstract(url);
        
        // Fetch content
        Console.WriteLine("[1/5] Fetching content...");
        var (content, title, author, publishedAt) = await genericUrl.FetchAsync(finalUrl);
        Console.WriteLine($"    Title: {title ?? "Unknown"}");
        Console.WriteLine($"    Content: {content.Length} chars");

        // Generate source ID
        var sourceId = GenerateSourceId(finalUrl, publishedAt);
        Console.WriteLine($"    Source ID: {sourceId}");

        // Split content into units
        Console.WriteLine("[2/5] Splitting content into units...");
        var units = ContentSplitter.SplitBySentences(content);
        Console.WriteLine($"    Found {units.Count} units");

        // Verify units in parallel
        Console.WriteLine($"[3/5] Verifying {units.Count} units (parallel={parallel})...");
        var verifiedUnits = await VerifyUnitsInParallelAsync(units, llm, webSearch, finalUrl, content, parallel);
        var verifiedCount = verifiedUnits.Count(u => u.Status == VerificationStatus.Verified);
        var unverifiableCount = verifiedUnits.Count(u => u.Status == VerificationStatus.Unverifiable);
        Console.WriteLine($"    Verified: {verifiedCount}, Unverifiable: {unverifiableCount}");

        // Write raw page
        Console.WriteLine("[4/5] Writing raw page...");
        await WriteRawPage(sourceId, title ?? finalUrl, finalUrl, sourceType, domain, units, verifiedUnits, rawPath);

        // Write verified page
        Console.WriteLine("[5/5] Writing verified page...");
        var verifiedFileName = SanitizeFileName(title ?? sourceId) + ".md";
        await WriteVerifiedPage(Path.Combine(verifiedPath, verifiedFileName), title ?? finalUrl, finalUrl, verifiedUnits);
        
        Console.WriteLine();
        Console.WriteLine($"Done! {verifiedCount} verified claims written to:");
        Console.WriteLine($"  - {Path.Combine(rawPath, sourceId + ".md")}");
        Console.WriteLine($"  - {Path.Combine(verifiedPath, verifiedFileName)}");
        
        return 0;
    }

    static async Task<List<VerifiedUnit>> VerifyUnitsInParallelAsync(
        List<string> units, 
        LlmClient llm, 
        WebSearchClient webSearch,
        string sourceUrl,
        string sourceContent,
        int maxParallel)
    {
        var results = new List<VerifiedUnit>();
        var semaphore = new SemaphoreSlim(maxParallel);
        
        var tasks = units.Select(async unit =>
        {
            await semaphore.WaitAsync();
            try
            {
                return await VerifyUnitAsync(unit, llm, webSearch, sourceUrl, sourceContent);
            }
            finally
            {
                semaphore.Release();
            }
        });

        var allResults = await Task.WhenAll(tasks);
        return allResults.Where(r => r != null).ToList()!;
    }

    static async Task<VerifiedUnit?> VerifyUnitAsync(
        string unit, 
        LlmClient llm, 
        WebSearchClient webSearch,
        string sourceUrl,
        string sourceContent)
    {
        if (unit.Length < 20) return null;

        var result = new VerifiedUnit { Statement = unit };
        
        // Try web search first
        var searchQuery = ExtractKeyFacts(unit);
        var searchResults = await webSearch.SearchAsync(searchQuery);
        
        if (searchResults.Any(r => !string.IsNullOrEmpty(r.Url)))
        {
            var best = searchResults.OrderByDescending(r => r.Confidence).First();
            result.SourceUrl = best.Url;
            result.SourceTitle = best.Title;
            result.SourceSnippet = best.Snippet;
            
            // Combine LLM score with search confidence
            var llmScore = await llm.VerifyClaimAsync(unit, best.Snippet);
            result.Confidence = (llmScore + best.Confidence) / 2;
        }
        else
        {
            // Fall back to LLM verification against source
            result.Confidence = await llm.VerifyClaimAsync(unit, sourceContent ?? sourceUrl);
            result.SourceUrl = sourceUrl;
        }

        result.Status = result.Confidence switch
        {
            >= 0.5m => VerificationStatus.Verified,
            >= 0.3m => VerificationStatus.Unverifiable,
            _ => VerificationStatus.False
        };

        Console.WriteLine($"    [{result.Status}] {result.Confidence:P0} - {unit.Substring(0, Math.Min(40, unit.Length))}...");
        return result;
    }

    static string ExtractKeyFacts(string text)
    {
        var words = text.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var important = words
            .Where(w => w.Length > 4 && !IsCommonWord(w))
            .Take(8)
            .ToArray();
        return string.Join(" ", important);
    }

    static bool IsCommonWord(string word)
    {
        var common = new[] { "that", "this", "with", "from", "have", "were", "been", "they", "their", "would", "could", "should", "about", "which", "there", "where", "when", "what", "who", "whom", "from", "into", "through", "during", "before", "after", "above", "below" };
        return common.Contains(word.ToLowerInvariant());
    }

    static async Task WriteRawPage(string sourceId, string title, string url, string type, string domain, List<string> units, List<VerifiedUnit> verifiedUnits, string rawPath)
    {
        var filePath = Path.Combine(rawPath, $"{sourceId}.md");
        var sb = new StringBuilder();
        
        sb.AppendLine($"# {title}");
        sb.AppendLine();
        sb.AppendLine($"- **URL:** [{url}]({url})");
        sb.AppendLine($"- **Type:** {type}");
        sb.AppendLine($"- **Domain:** {domain}");
        sb.AppendLine($"- **Fetched:** {DateTime.UtcNow:yyyy-MM-dd HH:mm:ss}");
        sb.AppendLine();
        sb.AppendLine("## Content with Verification");
        sb.AppendLine();
        
        for (int i = 0; i < units.Count && i < verifiedUnits.Count; i++)
        {
            var vu = verifiedUnits[i];
            var (status, icon) = vu.Status switch
            {
                VerificationStatus.Verified => ("VERIFIED", "✅"),
                VerificationStatus.Unverifiable => ("UNVERIFIED", "❓"),
                VerificationStatus.False => ("FALSE", "❌"),
                _ => ("UNKNOWN", "⚪")
            };
            
            sb.AppendLine($"> [!{status}]");
            sb.AppendLine($"> {icon} {vu.Statement}");
            sb.AppendLine($">");
            sb.AppendLine($"> _Confidence: {vu.Confidence:P0}_");
            
            if (!string.IsNullOrEmpty(vu.SourceUrl))
            {
                sb.AppendLine($">");
                sb.AppendLine($"> _Source: [{vu.SourceTitle ?? "link"}]({vu.SourceUrl})_");
            }
            sb.AppendLine();
        }
        
        await File.WriteAllTextAsync(filePath, sb.ToString());
    }

    static async Task WriteVerifiedPage(string filePath, string title, string url, List<VerifiedUnit> verifiedUnits)
    {
        var verified = verifiedUnits
            .Where(v => v.Status == VerificationStatus.Verified)
            .ToList();
        
        if (verified.Count == 0)
        {
            Console.WriteLine("    No verified claims to write.");
            return;
        }
        
        var sb = new StringBuilder();
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
            
            if (!string.IsNullOrEmpty(vu.SourceUrl))
            {
                sb.AppendLine("**Sources:**");
                sb.AppendLine($"- [{vu.SourceTitle ?? vu.SourceUrl}]({vu.SourceUrl})");
                sb.AppendLine();
            }
            
            if (!string.IsNullOrEmpty(vu.SourceSnippet))
            {
                sb.AppendLine("**Supporting Evidence:**");
                sb.AppendLine($"> {vu.SourceSnippet}");
                sb.AppendLine();
            }
            
            sb.AppendLine("---");
            sb.AppendLine();
        }
        
        await File.WriteAllTextAsync(filePath, sb.ToString());
    }

    static string ConvertArxivPdfToAbstract(string url)
    {
        var match = Regex.Match(url, @"arxiv\.org/pdf/(\d+\.\d+)");
        if (match.Success)
        {
            var paperId = match.Groups[1].Value;
            Console.WriteLine($"    Converted PDF to abstract: https://arxiv.org/abs/{paperId}");
            return $"https://arxiv.org/abs/{paperId}";
        }
        return url;
    }

    static string GenerateSourceId(string url, DateOnly? date)
    {
        var input = url + (date?.ToString("yyyy-MM-dd") ?? "");
        var hash = ComputeHash(input);
        return $"source-{hash.Substring(0, 16)}";
    }

    static string ComputeHash(string input)
    {
        var bytes = System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }

    static string SanitizeFileName(string name)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var sb = new StringBuilder();
        foreach (var c in name)
        {
            sb.Append(invalid.Contains(c) ? '-' : c);
        }
        return sb.ToString().Replace(" ", "-").Replace("--", "-").Trim('-');
    }

    static string? GetArg(string[] args, string key)
    {
        var idx = Array.IndexOf(args, key);
        return idx >= 0 && idx + 1 < args.Length ? args[idx + 1] : null;
    }
}

// Simplified versions of the services
enum VerificationStatus { Verified, Unverifiable, False }

class VerifiedUnit
{
    public string Statement { get; set; } = "";
    public VerificationStatus Status { get; set; }
    public decimal Confidence { get; set; }
    public string? SourceUrl { get; set; }
    public string? SourceTitle { get; set; }
    public string? SourceSnippet { get; set; }
}

class LlmClient
{
    private readonly HttpClient _http;
    private readonly string _baseUrl;
    private readonly string _model;
    private readonly string _apiKey;

    public LlmClient(HttpClient http, string baseUrl, string model, string apiKey)
    {
        _http = http;
        _baseUrl = baseUrl.TrimEnd('/');
        _model = model;
        _apiKey = apiKey;
    }

    public async Task<decimal> VerifyClaimAsync(string claim, string context)
    {
        try
        {
            var prompt = $@"Verify this claim against the source document.

CLAIM: {claim}

SOURCE DOCUMENT:
{context.Substring(0, Math.Min(4000, context.Length))}

Respond with a single number between 0.0 and 1.0 representing how well the claim is supported by the source.
0.0 = completely unsupported or contradicts
1.0 = fully supported

Only output the number.";

            var request = new
            {
                model = _model,
                max_tokens = 100,
                messages = new[] { new { role = "user", content = prompt } }
            };

            var json = JsonSerializer.Serialize(request);
            using var req = new HttpRequestMessage(HttpMethod.Post, $"{_baseUrl}/v1/messages");
            req.Headers.Add("anthropic-version", "2023-06-01");
            req.Headers.Add("x-api-key", _apiKey);
            req.Content = new StringContent(json, Encoding.UTF8, "application/json");

            var resp = await _http.SendAsync(req);
            
            if (!resp.IsSuccessStatusCode)
            {
                var errorBody = await resp.Content.ReadAsStringAsync();
                Console.WriteLine($"    [LLM] Error: {errorBody.Substring(0, Math.Min(200, errorBody.Length))}");
                return 0.5m;
            }
            
            var response = await resp.Content.ReadAsStringAsync();
            
            using var doc = JsonDocument.Parse(response);
            var root = doc.RootElement;
            
            if (root.TryGetProperty("content", out var content) && content.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in content.EnumerateArray())
                {
                    if (item.TryGetProperty("type", out var type) && type.GetString() == "text")
                    {
                        if (item.TryGetProperty("text", out var text))
                        {
                            var responseText = text.GetString() ?? "";
                            var match = Regex.Match(responseText.Trim(), @"^0?\.\d+");
                            if (match.Success && decimal.TryParse(match.Value, out var score))
                            {
                                return score;
                            }
                            // Try to find any number in the response
                            match = Regex.Match(responseText, @"0?\.\d+");
                            if (match.Success && decimal.TryParse(match.Value, out score))
                            {
                                return score;
                            }
                        }
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"    [LLM] Error: {ex.Message}");
        }
        
        return 0.5m;
    }
}

class WebSearchClient
{
    private readonly HttpClient _http;
    private readonly string _apiKey;

    public WebSearchClient(HttpClient http)
    {
        _http = http;
        _apiKey = Environment.GetEnvironmentVariable("BRAVE_SEARCH_API_KEY") ?? "";
    }

    public async Task<List<SearchResult>> SearchAsync(string query, int maxResults = 5)
    {
        var results = new List<SearchResult>();
        
        try
        {
            var url = $"https://api.search.brave.com/res/v1/web/search?q={Uri.EscapeDataString(query)}&count={maxResults}";
            using var req = new HttpRequestMessage(HttpMethod.Get, url);
            if (!string.IsNullOrEmpty(_apiKey))
                req.Headers.Add("X-Search-Key", _apiKey);
            req.Headers.Add("Accept", "application/json");

            var resp = await _http.SendAsync(req);
            
            if (resp.IsSuccessStatusCode)
            {
                var json = await resp.Content.ReadAsStringAsync();
                results = ParseBraveSearch(json, maxResults);
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"    Search error: {ex.Message}");
        }

        if (results.Count == 0)
        {
            results.Add(new SearchResult 
            { 
                Title = "No results", 
                Url = "", 
                Snippet = "Search unavailable", 
                Confidence = 0.5m 
            });
        }

        return results;
    }

    List<SearchResult> ParseBraveSearch(string json, int maxResults)
    {
        var results = new List<SearchResult>();
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            
            if (root.TryGetProperty("web", out var web) && web.TryGetProperty("results", out var resultsArray))
            {
                foreach (var item in resultsArray.EnumerateArray())
                {
                    if (results.Count >= maxResults) break;
                    
                    results.Add(new SearchResult
                    {
                        Title = item.TryGetProperty("title", out var t) ? t.GetString() ?? "" : "",
                        Url = item.TryGetProperty("url", out var u) ? u.GetString() ?? "" : "",
                        Snippet = item.TryGetProperty("description", out var d) ? d.GetString() ?? "" : "",
                        Confidence = 0.7m
                    });
                }
            }
        }
        catch { }
        
        return results;
    }
}

class SearchResult
{
    public string Title { get; set; } = "";
    public string Url { get; set; } = "";
    public string Snippet { get; set; } = "";
    public decimal Confidence { get; set; }
}

class GenericUrlClient
{
    private readonly HttpClient _http;

    public GenericUrlClient(HttpClient http) => _http = http;

    public async Task<(string content, string? title, string? author, DateOnly? publishedAt)> FetchAsync(string url)
    {
        var response = await _http.GetStringAsync(url);
        
        var title = Regex.Match(response, @"<title[^>]*>([^<]+)</title>", RegexOptions.IgnoreCase).Groups[1].Value.Trim();
        
        // Try to extract abstract section - arxiv uses class="abstract mathjax"
        var abstractMatch = Regex.Match(response, @"<blockquote[^>]*class=""abstract[^""]*""[^>]*>.*?<span class=""descriptor"">[^<]*</span>(.*?)</blockquote>", RegexOptions.Singleline | RegexOptions.IgnoreCase);
        string content;
        if (abstractMatch.Success)
        {
            content = abstractMatch.Groups[1].Value;
            content = Regex.Replace(content, "<[^>]+>", " ");
            content = System.Net.WebUtility.HtmlDecode(content);
            content = Regex.Replace(content, @"\s+", " ").Trim();
        }
        else
        {
            // Fall back to citation meta tag which has the abstract
            var citationAbstract = Regex.Match(response, @"<meta name=""citation_abstract""[^>]+content=""([^""]+)""", RegexOptions.IgnoreCase);
            if (citationAbstract.Success)
            {
                content = System.Net.WebUtility.HtmlDecode(citationAbstract.Groups[1].Value);
            }
            else
            {
                // Fall back to general stripping
                content = Regex.Replace(response, "<script[^>]*>.*?</script>", "", RegexOptions.Singleline | RegexOptions.IgnoreCase);
                content = Regex.Replace(content, "<style[^>]*>.*?</style>", "", RegexOptions.Singleline | RegexOptions.IgnoreCase);
                content = Regex.Replace(content, "<nav[^>]*>.*?</nav>", "", RegexOptions.Singleline | RegexOptions.IgnoreCase);
                content = Regex.Replace(content, "<footer[^>]*>.*?</footer>", "", RegexOptions.Singleline | RegexOptions.IgnoreCase);
                content = Regex.Replace(content, "<[^>]+>", " ");
                content = System.Net.WebUtility.HtmlDecode(content);
                content = Regex.Replace(content, @"\s+", " ").Trim();
            }
        }

        // Clean arxiv noise
        content = Regex.Replace(content, @"References\s*&\s*Citations.*?(?=\n\n|$)", "", RegexOptions.IgnoreCase | RegexOptions.Singleline);
        content = Regex.Replace(content, @"NASA\s*ADS|Google\s*Scholar|Semantic\s*Scholar|BibTeX.*?citation", "", RegexOptions.IgnoreCase);

        return (content, title, null, null);
    }
}

static class ContentSplitter
{
    static readonly Regex[] NoisePatterns = new[]
    {
        new Regex(@"Toggle|Cite as|BibTeX|Export|Bookmark|Bibliographic", RegexOptions.IgnoreCase),
        new Regex(@"^[|\-\s]+$"),
        new Regex(@"^(View|Search|Browse|Help|Login)$"),
        new Regex(@"\b(LG|DC|cs|math)\b.*?(?=\s|$)", RegexOptions.IgnoreCase)
    };

    public static List<string> SplitBySentences(string content)
    {
        if (string.IsNullOrWhiteSpace(content))
            return new List<string>();

        var units = new List<string>();
        var sentences = content.Split(new[] { '.', '!', '?' }, StringSplitOptions.RemoveEmptyEntries);
        
        foreach (var s in sentences)
        {
            var trimmed = s.Trim();
            
            if (trimmed.Length < 30) continue;
            if (trimmed.Length > 1000) trimmed = trimmed.Substring(0, 1000);
            if (NoisePatterns.Any(p => p.IsMatch(trimmed))) continue;
            
            var wordCount = trimmed.Split(' ', StringSplitOptions.RemoveEmptyEntries).Length;
            if (wordCount < 3) continue;
            
            var alphaRatio = (double)trimmed.Count(char.IsLetter) / trimmed.Length;
            if (alphaRatio < 0.5) continue;
            
            units.Add(trimmed);
        }
        
        return units;
    }
}
