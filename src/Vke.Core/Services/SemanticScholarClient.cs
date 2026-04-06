using System.Net.Http.Json;
using System.Text.Json.Serialization;

namespace Vke.Core.Services;

public class SemanticScholarClient
{
    private readonly HttpClient _http;
    private readonly string _apiKey;

    public SemanticScholarClient(HttpClient http, string? apiKey = null)
    {
        _http = http;
        _apiKey = apiKey ?? "";
    }

    public async Task<SemanticScholarPaper> GetPaperAsync(string doiOrArxivId)
    {
        var fields = "authors,title,abstract,references";
        var request = new HttpRequestMessage(HttpMethod.Get, 
            $"https://api.semanticscholar.org/graph/v1/paper/{doiOrArxivId}?fields={fields}");
        
        if (!string.IsNullOrEmpty(_apiKey))
            request.Headers.Add("x-api-key", _apiKey);

        var response = await _http.SendAsync(request);
        response.EnsureSuccessStatusCode();
        
        var paper = await response.Content.ReadFromJsonAsync<SemanticScholarPaper>();
        if (paper == null)
            throw new InvalidOperationException("Failed to deserialize paper response");
        return paper;
    }
}

public class SemanticScholarPaper
{
    [JsonPropertyName("paperId")]
    public string? PaperId { get; set; }
    [JsonPropertyName("title")]
    public string? Title { get; set; }
    [JsonPropertyName("abstract")]
    public string? Abstract { get; set; }
    [JsonPropertyName("authors")]
    public List<SemanticScholarAuthor> Authors { get; set; } = new();
    [JsonPropertyName("references")]
    public List<SemanticScholarReference> References { get; set; } = new();
}

public class SemanticScholarAuthor
{
    [JsonPropertyName("name")]
    public string? Name { get; set; }
}

public class SemanticScholarReference
{
    [JsonPropertyName("title")]
    public string? Title { get; set; }
    [JsonPropertyName("paperId")]
    public string? PaperId { get; set; }
}