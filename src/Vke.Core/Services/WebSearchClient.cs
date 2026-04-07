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
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[WebSearchClient] Search failed: {ex.Message}");
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
    public static List<string> SplitByParagraphs(string content)
    {
        if (string.IsNullOrWhiteSpace(content))
            return new List<string>();

        var paragraphs = content.Split(new[] { "\n\n", "\r\n\r\n", "\n" }, StringSplitOptions.RemoveEmptyEntries);
        return paragraphs.Where(p => p.Trim().Length > 20).Select(p => p.Trim()).ToList();
    }

    public static List<string> SplitBySentences(string content)
    {
        if (string.IsNullOrWhiteSpace(content))
            return new List<string>();

        var sentenceEnders = new[] { '.', '!', '?' };
        var sentences = new List<string>();
        var current = "";

        foreach (var c in content)
        {
            current += c;
            if (sentenceEnders.Contains(c))
            {
                var trimmed = current.Trim();
                if (trimmed.Length > 20)
                    sentences.Add(trimmed);
                current = "";
            }
        }

        if (current.Trim().Length > 20)
            sentences.Add(current.Trim());

        return sentences;
    }
}
