using System.Text.RegularExpressions;

namespace Vke.Core.Services;

public class GenericUrlClient
{
    private readonly HttpClient _http;

    public GenericUrlClient(HttpClient http)
    {
        _http = http;
    }

    public async Task<(string content, string? title, string? author, DateOnly? publishedAt)> FetchAsync(string url)
    {
        var response = await _http.GetStringAsync(url);
        
        var title = ExtractTitle(response);
        var author = ExtractAuthor(response);
        var publishedAt = ExtractPublishedDate(response);
        
        var content = StripHtmlTags(response);
        
        return (content, title, author, publishedAt);
    }

    private static string ExtractTitle(string html)
    {
        var match = Regex.Match(html, @"<title[^>]*>([^<]+)</title>", RegexOptions.IgnoreCase);
        return match.Success ? match.Groups[1].Value.Trim() : null;
    }

    private static string? ExtractAuthor(string html)
    {
        var authorMatch = Regex.Match(html, @"<meta[^>]+name=""author""[^>]+content=""([^""]+)""", RegexOptions.IgnoreCase);
        if (authorMatch.Success) return authorMatch.Groups[1].Value;
        
        var ogAuthorMatch = Regex.Match(html, @"<meta[^>]+property=""article:author""[^>]+content=""([^""]+)""", RegexOptions.IgnoreCase);
        if (ogAuthorMatch.Success) return ogAuthorMatch.Groups[1].Value;
        
        return null;
    }

    private static DateOnly? ExtractPublishedDate(string html)
    {
        var patterns = new[]
        {
            @"<time[^>]+datetime=""([^""]+)""",
            @"<meta[^>]+property=""article:published_time""[^>]+content=""([^""]+)""",
            @"(\d{4}-\d{2}-\d{2})",
        };
        
        foreach (var pattern in patterns)
        {
            var match = Regex.Match(html, pattern);
            if (match.Success && DateOnly.TryParse(match.Groups[1].Value[..10], out var date))
                return date;
        }
        
        return null;
    }

    private static string StripHtmlTags(string html)
    {
        return Regex.Replace(html, "<[^>]*>", " ")
            .Replace("&nbsp;", " ")
            .Replace("&amp;", "&")
            .Replace("&lt;", "<")
            .Replace("&gt;", ">");
    }
}