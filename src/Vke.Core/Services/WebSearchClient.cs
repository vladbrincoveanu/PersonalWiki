using System.Text.Json;

namespace Vke.Core.Services;

public class WebSearchResult
{
    public string Title { get; set; } = "";
    public string Url { get; set; } = "";
    public string Snippet { get; set; } = "";
    public decimal Confidence { get; set; }
}

public class WebSearchClient
{
    private readonly HttpClient _http;
    private readonly string _apiKey;
    private readonly string _baseUrl;

    public WebSearchClient(HttpClient http, string? apiKey = null, string? baseUrl = null)
    {
        _http = http;
        _apiKey = apiKey ?? Environment.GetEnvironmentVariable("BRAVE_SEARCH_API_KEY") ?? "";
        _baseUrl = baseUrl ?? Environment.GetEnvironmentVariable("SEARCH_BASE_URL") ?? "https://api.search.brave.com/res/v1/web/search";
    }

    public async Task<List<WebSearchResult>> SearchAsync(string query, int maxResults = 5)
    {
        var results = new List<WebSearchResult>();
        
        try
        {
            var request = new HttpRequestMessage(HttpMethod.Get, $"{_baseUrl}?q={Uri.EscapeDataString(query)}&count={maxResults}");
            if (!string.IsNullOrEmpty(_apiKey))
            {
                request.Headers.Add("X-Search-Key", _apiKey);
            }
            request.Headers.Add("Accept", "application/json");

            var response = await _http.SendAsync(request);
            if (response.IsSuccessStatusCode)
            {
                var json = await response.Content.ReadAsStringAsync();
                results = ParseBraveSearch(json, maxResults);
            }
            else
            {
                Console.Error.WriteLine($"[WebSearchClient] Search request failed with status {response.StatusCode}");
            }
        }
        catch (HttpRequestException ex)
        {
            Console.Error.WriteLine($"[WebSearchClient] HTTP request failed: {ex.Message}");
        }
        catch (TaskCanceledException ex)
        {
            Console.Error.WriteLine($"[WebSearchClient] Search request timed out: {ex.Message}");
        }

        if (results.Count == 0)
        {
            results.Add(new WebSearchResult
            {
                Title = "No external sources found",
                Url = "",
                Snippet = "Web search unavailable - claims marked as unverified",
                Confidence = 0.5m
            });
        }

        return results;
    }

    private List<WebSearchResult> ParseBraveSearch(string json, int maxResults)
    {
        var results = new List<WebSearchResult>();
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            
            if (root.TryGetProperty("web", out var web) && 
                web.TryGetProperty("results", out var resultsArray))
            {
                foreach (var item in resultsArray.EnumerateArray())
                {
                    if (results.Count >= maxResults) break;
                    
                    var title = item.TryGetProperty("title", out var t) ? t.GetString() ?? "" : "";
                    var url = item.TryGetProperty("url", out var u) ? u.GetString() ?? "" : "";
                    var snippet = item.TryGetProperty("description", out var s) ? s.GetString() ?? "" : "";
                    
                    results.Add(new WebSearchResult
                    {
                        Title = title,
                        Url = url,
                        Snippet = snippet,
                        Confidence = CalculateConfidence(snippet)
                    });
                }
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[WebSearchClient] Parse failed: {ex.Message}");
        }
        return results;
    }

    private decimal CalculateConfidence(string snippet)
    {
        if (string.IsNullOrWhiteSpace(snippet)) return 0.5m;
        if (snippet.Length > 100) return 0.7m;
        if (snippet.Length > 50) return 0.6m;
        return 0.5m;
    }
}

public class ContentSplitter
{
    private static readonly string[] NoisePrefixes = { "Toggle", "View", "Cite", "Export", "Share", "Download", "Print", "Back to", "Previous", "Next", "Skip to", "Table of Contents" };
    private static readonly string[] NoisePatterns = { "BibTeX", "citation", "Formatted citation", "Reference", "References", "doi:", "arXiv:", "ISSN", "ISBN", "PMID:", "PMCID:" };
    private static readonly string[] Verbs = { "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must", "shall", "can", "show", "shows", "showed", "demonstrate", "demonstrates", "demonstrated", "propose", "proposes", "proposed", "present", "presents", "presented", "describe", "describes", "described", "introduce", "introduces", "introduced", "suggest", "suggests", "suggested", "indicate", "indicates", "indicated", "reveal", "reveals", "revealed", "find", "finds", "found", "observe", "observes", "observed", "report", "reports", "reported", "provide", "provides", "provided", "offer", "offers", "offered", "develop", "develops", "developed", "create", "creates", "created", "use", "uses", "used", "apply", "applies", "applied", "achieve", "achieves", "achieved", "improve", "improves", "improved", "enable", "enables", "enabled", "reduce", "reduces", "reduced", "increase", "increases", "increased", "decrease", "decreases", "decreased", "generate", "generates", "generated", "produce", "produces", "produced", "represent", "represents", "represented", "suggest", "suggests", "suggested", "identify", "identifies", "identified", "explore", "explores", "explored", "investigate", "investigates", "investigated", "examine", "examines", "examined", "analyze", "analyzes", "analyzed", "synthesize", "synthesizes", "synthesized" };

    public static List<string> SplitByParagraphs(string content)
    {
        if (string.IsNullOrWhiteSpace(content))
            return new List<string>();

        var paragraphs = content.Split(new[] { "\n\n", "\r\n\r\n" }, StringSplitOptions.RemoveEmptyEntries);
        var result = new List<string>();
        var abstractBuilder = new System.Text.StringBuilder();
        var inAbstract = false;

        foreach (var para in paragraphs)
        {
            var trimmed = para.Trim();
            if (trimmed.Length <= 15) continue;

            if (trimmed.StartsWith("Abstract", StringComparison.OrdinalIgnoreCase) && trimmed.Length < 200)
            {
                inAbstract = true;
                abstractBuilder.Clear();
                abstractBuilder.Append(trimmed);
            }
            else if (inAbstract && (trimmed.StartsWith("Keywords", StringComparison.OrdinalIgnoreCase) || trimmed.StartsWith("1.", StringComparison.Ordinal) || trimmed.StartsWith("Introduction", StringComparison.OrdinalIgnoreCase)))
            {
                var abstractText = abstractBuilder.ToString();
                if (abstractText.Length > 30)
                    result.Add(abstractText);
                inAbstract = false;
                result.Add(trimmed);
            }
            else if (inAbstract)
            {
                abstractBuilder.Append(" ").Append(trimmed);
            }
            else
            {
                result.Add(trimmed);
            }
        }

        if (inAbstract && abstractBuilder.Length > 30)
        {
            result.Add(abstractBuilder.ToString());
        }

        return result;
    }

    public static List<string> SplitBySentences(string content)
    {
        if (string.IsNullOrWhiteSpace(content))
            return new List<string>();

        var paragraphSplit = SplitByParagraphs(content);
        if (paragraphSplit.Count > 3)
            return FilterFragments(paragraphSplit);

        var sentenceEnders = new[] { '.', '!', '?' };
        var sentences = new List<string>();
        var current = new System.Text.StringBuilder();

        foreach (var c in content)
        {
            current.Append(c);
            if (sentenceEnders.Contains(c))
            {
                var trimmed = current.ToString().Trim();
                if (trimmed.Length > 20)
                    sentences.Add(trimmed);
                current.Clear();
            }
        }

        if (current.Length > 20)
            sentences.Add(current.ToString().Trim());

        return FilterFragments(sentences);
    }

    private static List<string> FilterFragments(List<string> fragments)
    {
        var filtered = new List<string>();
        var seen = new HashSet<string>();

        foreach (var fragment in fragments)
        {
            var cleaned = CleanFragment(fragment);
            if (string.IsNullOrWhiteSpace(cleaned)) continue;
            if (IsNoise(cleaned)) continue;
            if (!IsMeaningful(cleaned)) continue;
            if (cleaned.Length < 50 && !ContainsVerb(cleaned)) continue;
            if (seen.Contains(cleaned)) continue;

            seen.Add(cleaned);
            filtered.Add(cleaned);
        }

        return filtered;
    }

    private static string CleanFragment(string fragment)
    {
        var cleaned = fragment.Trim();
        while (cleaned.Length > 0 && (char.IsPunctuation(cleaned[0]) || char.IsWhiteSpace(cleaned[0])))
            cleaned = cleaned.Substring(1);
        while (cleaned.Length > 0 && (char.IsPunctuation(cleaned[cleaned.Length - 1]) || char.IsWhiteSpace(cleaned[cleaned.Length - 1])))
            cleaned = cleaned.Substring(0, cleaned.Length - 1);
        return cleaned.Trim();
    }

    private static readonly System.Text.RegularExpressions.Regex NumberedPatternRegex = new(@"^\d+[\.\)]\s*$");
    private static readonly System.Text.RegularExpressions.Regex FigurePatternRegex = new(@"^(Fig\.|Figure|Table|Eq\.|Equation)\s*\d", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
    private static readonly System.Text.RegularExpressions.Regex LgDcPatternRegex = new(@"^(LG|DC)\s*[\)\d]");

    private static bool IsNoise(string fragment)
    {
        if (string.IsNullOrWhiteSpace(fragment) || fragment.Length < 3) return true;
        if (NoisePrefixes.Any(p => fragment.StartsWith(p, StringComparison.OrdinalIgnoreCase))) return true;
        if (NoisePrefixes.Any(p => fragment.Contains(p, StringComparison.OrdinalIgnoreCase))) return true;
        if (NoisePatterns.Any(p => fragment.StartsWith(p, StringComparison.OrdinalIgnoreCase))) return true;
        if (NoisePatterns.Any(p => fragment.Contains(p, StringComparison.OrdinalIgnoreCase))) return true;
        if (fragment.StartsWith("[") && fragment.Contains("]") && fragment.Length < 50) return true;
        if (fragment.StartsWith("\"") && fragment.Contains("\"")) return true;
        if (NumberedPatternRegex.IsMatch(fragment)) return true;
        if (FigurePatternRegex.IsMatch(fragment)) return true;
        if (LgDcPatternRegex.IsMatch(fragment)) return true;
        if (fragment.Contains("|")) return true;
        if (fragment.Contains("prev | next")) return true;
        return false;
    }

    private static bool IsMeaningful(string fragment)
    {
        var words = fragment.Split(new[] { ' ', '\t', '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
        if (words.Length < 2) return false;

        var alphaCount = words.Sum(w => w.Count(char.IsLetter));
        if (alphaCount < fragment.Length * 0.5) return false;

        return true;
    }

    private static bool ContainsVerb(string fragment)
    {
        var words = fragment.ToLowerInvariant().Split(new[] { ' ', '\t', '\n', '\r', ',', ';', ':', '(', ')', '[', ']', '"', '\'', '.', '!', '?' }, StringSplitOptions.RemoveEmptyEntries);
        return words.Any(w => Verbs.Contains(w));
    }
}
