using System.Net.Http.Json;
using System.Text.Json;
using Vke.Core.Data.Models;
using Vke.Core.Utils;

namespace Vke.Core.Services;

public interface ILlmClient
{
    Task<List<Claim>> ExtractClaimsAsync(string content, string sourceType);
    Task<decimal> VerifyClaimAsync(string claim, string sourceContent);
}

public class LlmClient : ILlmClient
{
    private readonly HttpClient _http;
    private readonly string _baseUrl;
    private readonly JsonSerializerOptions _jsonOptions = new() { PropertyNameCaseInsensitive = true };

    public LlmClient(HttpClient http, string baseUrl)
    {
        _http = http;
        _baseUrl = baseUrl.TrimEnd('/');
    }

    public async Task<List<Claim>> ExtractClaimsAsync(string content, string sourceType)
    {
        var prompt = $@"You are a factual claim extractor. Extract all verifiable claims from this document.

Rules:
- One claim per line
- Each claim must be a complete, self-contained sentence
- Resolve all pronouns
- Split compound claims
- Skip opinions, predictions, forward-looking statements
- For financial claims: always include entity name, metric, value, and time period

Output format (one per line):
CLAIM: [the atomic claim]
LOCATION: [section or page where found]

Document:
{content[..Math.Min(content.Length, 8000)]}";

        var response = await _http.PostAsJsonAsync($"{_baseUrl}/chat/completions", new
        {
            model = "local",
            messages = new[] { new { role = "user", content = prompt } },
            temperature = 0.1m,
        });

        var result = await response.Content.ReadFromJsonAsync<LlmChatResponse>(_jsonOptions);
        var llmContent = result?.Choices?.FirstOrDefault()?.Message?.Content ?? "";

        return ClaimParser.ParseLlmOutput(llmContent);
    }

    public async Task<decimal> VerifyClaimAsync(string claim, string sourceContent)
    {
        var prompt = $@"Verify this claim against the source document.

CLAIM: {claim}

SOURCE DOCUMENT:
{sourceContent[..Math.Min(sourceContent.Length, 8000)]}

Respond with a single number between 0.0 and 1.0 representing how well the claim is supported by the source.
0.0 = completely unsupported or contradicts
1.0 = fully supported

Only output the number.";

        var response = await _http.PostAsJsonAsync($"{_baseUrl}/chat/completions", new
        {
            model = "local",
            messages = new[] { new { role = "user", content = prompt } },
            temperature = 0.1m,
        });

        var result = await response.Content.ReadFromJsonAsync<LlmChatResponse>(_jsonOptions);
        var scoreText = result?.Choices?.FirstOrDefault()?.Message?.Content?.Trim() ?? "0";

        return decimal.TryParse(scoreText, out var score) ? score : 0m;
    }
}

internal class LlmChatResponse
{
    public List<LlmChoice>? Choices { get; set; }
}

internal class LlmChoice
{
    public LlmMessage? Message { get; set; }
}

internal class LlmMessage
{
    public string? Content { get; set; }
}
