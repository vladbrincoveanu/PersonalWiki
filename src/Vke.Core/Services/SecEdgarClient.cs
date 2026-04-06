using System.Net.Http.Json;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Vke.Core.Services;

public class SecEdgarClient
{
    private readonly HttpClient _http;
    private const string SecGovBase = "https://www.sec.gov";
    private Dictionary<string, string>? _cikCache;

    public SecEdgarClient(HttpClient http)
    {
        _http = http;
        _http.DefaultRequestHeaders.Add("User-Agent", "VKE Research v1 (your@email.com)");
    }

    public async Task<string> GetCompanyCikAsync(string ticker)
    {
        if (_cikCache == null)
            await LoadCikCacheAsync();

        var upperTicker = ticker.ToUpper();
        if (_cikCache.TryGetValue(upperTicker, out var cik))
            return cik;

        throw new InvalidOperationException($"Could not find CIK for ticker {ticker}");
    }

    private async Task LoadCikCacheAsync()
    {
        _cikCache = new Dictionary<string, string>();
        try
        {
            var response = await _http.GetStringAsync($"{SecGovBase}/files/company_tickers.json");
            using var doc = JsonDocument.Parse(response);
            foreach (var entry in doc.RootElement.EnumerateObject())
            {
                if (entry.Value.TryGetProperty("ticker", out var ticker) &&
                    entry.Value.TryGetProperty("cik_str", out var cik))
                {
                    var cikValue = cik.GetInt32().ToString().PadLeft(10, '0');
                    _cikCache[ticker.GetString()!.ToUpper()] = cikValue;
                }
            }
        }
        catch
        {
            _cikCache = new Dictionary<string, string>();
        }
    }

    public async Task<List<SecFiling>> GetFilingsAsync(string ticker, string formType)
    {
        var cik = await GetCompanyCikAsync(ticker);
        var cikNum = cik.TrimStart('0');
        var searchUrl = $"https://efts.sec.gov/LATEST/search-index?q={cik}+{formType}&forms={formType}";
        
        try
        {
            var response = await _http.GetStringAsync(searchUrl);
            using var doc = JsonDocument.Parse(response);
            var hits = doc.RootElement.GetProperty("hits").GetProperty("hits");
            
            var filings = new List<SecFiling>();
            foreach (var hit in hits.EnumerateArray())
            {
                var source = hit.GetProperty("_source");
                if (source.TryGetProperty("ciks", out var ciks))
                {
                    var cikStrs = ciks.EnumerateArray().Select(c => c.GetString()!).ToList();
                    var cikMatches = cikStrs.Any(c => c == cikNum || c == cik);
                    if (!cikMatches) continue;
                    var adsh = source.GetProperty("adsh").GetString() ?? "";
                    var fileDate = source.TryGetProperty("file_date", out var fd) ? fd.GetString() : "";
                    var periodEnding = source.TryGetProperty("period_ending", out var pe) ? pe.GetString() : "";
                    
                    var adshRaw = adsh.Replace("-", "");
                    var period = string.IsNullOrEmpty(periodEnding) ? "unknown" : periodEnding.Replace("-", "").Substring(0, Math.Min(8, periodEnding.Length));
                    var docName = $"aapl-{period}.htm";
                    filings.Add(new SecFiling
                    {
                        FormType = formType,
                        AccessionNumber = adsh,
                        FilingDate = DateOnly.TryParse(fileDate, out var dt) ? dt : DateOnly.MinValue,
                        Url = $"{SecGovBase}/Archives/edgar/data/{cikNum}/{adshRaw}/{docName}",
                    });
                }
            }
            return filings.OrderByDescending(f => f.FilingDate).ToList();
        }
        catch
        {
            return new List<SecFiling>();
        }
    }

    public virtual async Task<string> FetchFilingContentAsync(string url)
    {
        var response = await _http.GetStringAsync(url);
        var content = StripHtmlTags(response);
        if (content.Contains("Not Found", StringComparison.OrdinalIgnoreCase) ||
            content.Contains("Error", StringComparison.OrdinalIgnoreCase) && content.Length < 200)
        {
            throw new InvalidOperationException($"SEC filing not found or error: {url}");
        }
        return content;
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