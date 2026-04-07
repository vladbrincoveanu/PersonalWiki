using System.Net.Http.Headers;
using System.Text;
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
    private readonly string _model;
    private readonly string _apiKey;
    private readonly JsonSerializerOptions _jsonOptions = new() { PropertyNameCaseInsensitive = true };

    public LlmClient(HttpClient http, string baseUrl, string model, string apiKey)
    {
        _http = http;
        _baseUrl = baseUrl.TrimEnd('/');
        _model = model;
        _apiKey = apiKey;
    }

    public async Task<List<Claim>> ExtractClaimsAsync(string content, string sourceType)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        Console.WriteLine($"[LlmClient] ExtractClaims started at {DateTime.UtcNow:HH:mm:ss.fff}");
        
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
{content[..Math.Min(content.Length, 4000)]}";

        Console.WriteLine($"[LlmClient] Prompt ready, sending request... elapsed={sw.ElapsedMilliseconds}ms");
        var responseText = await SendAnthropicMessageAsync(prompt);
        sw.Stop();
        Console.WriteLine($"[LlmClient] ExtractClaims completed in {sw.ElapsedMilliseconds}ms");
        return ClaimParser.ParseLlmOutput(responseText);
    }

    public async Task<decimal> VerifyClaimAsync(string claim, string sourceContent)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        Console.WriteLine($"[LlmClient] VerifyClaim started at {DateTime.UtcNow:HH:mm:ss.fff}");
        
        var prompt = $@"Verify this claim against the source document.

CLAIM: {claim}

SOURCE DOCUMENT:
{sourceContent[..Math.Min(sourceContent.Length, 8000)]}

Respond with a single number between 0.0 and 1.0 representing how well the claim is supported by the source.
0.0 = completely unsupported or contradicts
1.0 = fully supported

Only output the number.";

        var responseText = await SendAnthropicMessageAsync(prompt);
        sw.Stop();
        Console.WriteLine($"[LlmClient] VerifyClaim completed in {sw.ElapsedMilliseconds}ms");
        var scoreText = responseText.Trim();
        return decimal.TryParse(scoreText, out var score) ? score : 0m;
    }

    private async Task<string> SendAnthropicMessageAsync(string prompt)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        Console.WriteLine($"[LlmClient] SendAnthropicMessageAsync sending request at {DateTime.UtcNow:HH:mm:ss.fff}");
        
        var request = new HttpRequestMessage(HttpMethod.Post, $"{_baseUrl}/v1/messages");
        request.Headers.Add("anthropic-version", "2023-06-01");
        request.Headers.Add("x-api-key", _apiKey);

        var body = new
        {
            model = _model,
            max_tokens = 8192,
            messages = new[] { new { role = "user", content = prompt } }
        };

        var json = JsonSerializer.Serialize(body);
        request.Content = new StringContent(json, Encoding.UTF8, "application/json");

        Console.WriteLine($"[LlmClient] HTTP request start... elapsed={sw.ElapsedMilliseconds}ms");
        var response = await _http.SendAsync(request);
        sw.Stop();
        Console.WriteLine($"[LlmClient] HTTP response received in {sw.ElapsedMilliseconds}ms, status={response.StatusCode}");
        response.EnsureSuccessStatusCode();

        var responseJson = await response.Content.ReadAsStringAsync();
        Console.WriteLine($"[LlmClient] Response parsed in {sw.ElapsedMilliseconds}ms");
        var result = JsonSerializer.Deserialize<AnthropicResponse>(responseJson, _jsonOptions);
        var text = result?.Content?.FirstOrDefault(c => c.Type == "text")?.Text;
        if (string.IsNullOrEmpty(text))
            throw new InvalidOperationException("LLM response missing text content");
        return text;
    }
}

public class AnthropicResponse
{
    public List<AnthropicContentBlock>? Content { get; set; }
}

public class AnthropicContentBlock
{
    public string? Type { get; set; }
    public string? Text { get; set; }
}
