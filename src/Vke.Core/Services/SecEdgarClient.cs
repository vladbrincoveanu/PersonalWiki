using System.Net.Http.Json;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Vke.Core.Services;

public class SecEdgarClient
{
    private readonly HttpClient _http;
    private const string BaseUrl = "https://data.sec.gov/submissions";
    private const string SecGovBase = "https://www.sec.gov";

    public SecEdgarClient(HttpClient http)
    {
        _http = http;
        _http.DefaultRequestHeaders.Add("User-Agent", "VKE Research v1 (your@email.com)");
    }

    public async Task<string> GetCompanyCikAsync(string ticker)
    {
        var response = await _http.GetFromJsonAsync<SecSubmission>($"{BaseUrl}/CIK{ticker.PadLeft(10, '0')}.json");
        return response?.Cik ?? throw new InvalidOperationException($"Could not find CIK for ticker {ticker}");
    }

    public async Task<List<SecFiling>> GetFilingsAsync(string ticker, string formType)
    {
        var cik = await GetCompanyCikAsync(ticker);
        var submission = await _http.GetFromJsonAsync<SecSubmission>($"{BaseUrl}/CIK{cik.PadLeft(10, '0')}.json");
        
        var filings = new List<SecFiling>();
        var recent = submission?.Filings?.Recent;
        if (recent == null) return filings;

        for (int i = 0; i < recent.FormTypes.Count; i++)
        {
            if (recent.FormTypes[i] == formType)
            {
                filings.Add(new SecFiling
                {
                    FormType = recent.FormTypes[i],
                    AccessionNumber = recent.AccessionNumbers[i],
                    FilingDate = DateOnly.Parse(recent.FilingDates[i]),
                    Url = $"{SecGovBase}/Archives/edgar/data/{cik}/{recent.AccessionNumbers[i].Replace("-", "")}/{recent.PrimaryDocuments[i]}",
                });
            }
        }

        return filings;
    }

    public async Task<string> FetchFilingContentAsync(string url)
    {
        var response = await _http.GetStringAsync(url);
        return StripHtmlTags(response);
    }

    public static string StripHtmlTags(string html)
    {
        return Regex.Replace(html, "<[^>]*>", " ")
            .Replace("&nbsp;", " ")
            .Replace("&amp;", "&")
            .Replace("&lt;", "<")
            .Replace("&gt;", ">");
    }
}

public class SecSubmission
{
    public string? Cik { get; set; }
    public SecFilings? Filings { get; set; }
}

public class SecFilings
{
    public SecFilingRecent Recent { get; set; } = new();
}

public class SecFilingRecent
{
    public List<string> FormTypes { get; set; } = new();
    public List<string> AccessionNumbers { get; set; } = new();
    public List<string> FilingDates { get; set; } = new();
    public List<string> PrimaryDocuments { get; set; } = new();
}

public class SecFiling
{
    public string FormType { get; set; } = string.Empty;
    public string AccessionNumber { get; set; } = string.Empty;
    public DateOnly FilingDate { get; set; }
    public string Url { get; set; } = string.Empty;
}