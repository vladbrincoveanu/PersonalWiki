using System.Text.RegularExpressions;

namespace Vke.Core.Services;

public class GenericUrlClient
{
    private static readonly Regex TitleRegex = new(@"<title[^>]*>([^<]+)</title>", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex AuthorMetaRegex = new(@"<meta[^>]+name=""author""[^>]+content=""([^""]+)""", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex AuthorOgRegex = new(@"<meta[^>]+property=""article:author""[^>]+content=""([^""]+)""", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex TimeDatetimeRegex = new(@"<time[^>]+datetime=""([^""]+)""", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex PublishedTimeRegex = new(@"<meta[^>]+property=""article:published_time""[^>]+content=""([^""]+)""", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex DateRegex = new(@"(\d{4}-\d{2}-\d{2})", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex ScriptRegex = new("<script[^>]*>.*?</script>", RegexOptions.Singleline | RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex StyleRegex = new("<style[^>]*>.*?</style>", RegexOptions.Singleline | RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex NavRegex = new("<nav[^>]*>.*?</nav>", RegexOptions.Singleline | RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex FooterRegex = new("<footer[^>]*>.*?</footer>", RegexOptions.Singleline | RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex HeaderRegex = new("<header[^>]*>.*?</header>", RegexOptions.Singleline | RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex HtmlTagRegex = new("<[^>]+>", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex WhitespaceRegex = new(@"\s+", RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex ArxivUiNoiseRegex = new(
        @"References\s*&\s*Citations|NASA\s*ADS|Google\s*Scholar|Semantic\s*Scholar|Bibliographic\s*Explorer|Connected\s*Papers|Litmaps|ScienceCast|BibTeX\s*formatted\s*citation|export\s*BibTeX|Toggle\s*UI|Litmaps\s*Banner|Bibliographic\s*Tools|Bookmark|Demos|Replicate|Huggingface\s*Spaces|arXiv\s*Labs|Cite\s*as",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);
    private static readonly Regex CiteAsSectionRegex = new(@"Cite\s*as[:\s]*.*?(?=\n\n|\n[A-Z]|$)", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private readonly HttpClient _http;

    public GenericUrlClient(HttpClient http)
    {
        _http = http;
    }

    public async Task<(string content, string? title, string? author, DateOnly? publishedAt)> FetchAsync(string url)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        Console.WriteLine($"[GenericUrlClient] FetchAsync START {url} at {DateTime.UtcNow:HH:mm:ss.fff}");
        var response = await _http.GetStringAsync(url);
        sw.Stop();
        Console.WriteLine($"[GenericUrlClient] FetchAsync HTTP done in {sw.ElapsedMilliseconds}ms, response length={response.Length} for {url}");
        
        var title = ExtractTitle(response);
        var author = ExtractAuthor(response);
        var publishedAt = ExtractPublishedDate(response);
        
        var content = StripHtmlTags(response);
        Console.WriteLine($"[GenericUrlClient] Content length after strip={content.Length}");
        
        return (content, title, author, publishedAt);
    }

    private static string? ExtractTitle(string html)
    {
        var match = TitleRegex.Match(html);
        return match.Success ? match.Groups[1].Value.Trim() : null;
    }

    private static string? ExtractAuthor(string html)
    {
        var authorMatch = AuthorMetaRegex.Match(html);
        if (authorMatch.Success) return authorMatch.Groups[1].Value;
        
        var ogAuthorMatch = AuthorOgRegex.Match(html);
        if (ogAuthorMatch.Success) return ogAuthorMatch.Groups[1].Value;
        
        return null;
    }

    private static DateOnly? ExtractPublishedDate(string html)
    {
        var match = TimeDatetimeRegex.Match(html);
        if (match.Success && DateOnly.TryParse(match.Groups[1].Value[..10], out var date))
            return date;
        
        match = PublishedTimeRegex.Match(html);
        if (match.Success && DateOnly.TryParse(match.Groups[1].Value[..10], out date))
            return date;
        
        match = DateRegex.Match(html);
        if (match.Success && DateOnly.TryParse(match.Groups[1].Value[..10], out date))
            return date;
        
        return null;
    }

    private static string StripHtmlTags(string html)
    {
        var text = ScriptRegex.Replace(html, "");
        text = StyleRegex.Replace(text, "");
        text = NavRegex.Replace(text, "");
        text = FooterRegex.Replace(text, "");
        text = HeaderRegex.Replace(text, "");
        text = HtmlTagRegex.Replace(text, " ");
        text = System.Net.WebUtility.HtmlDecode(text);
        text = WhitespaceRegex.Replace(text, " ");
        text = text.Trim();
        
        if (html.Contains("arxiv.org", StringComparison.OrdinalIgnoreCase))
        {
            text = CleanArxivNoise(text);
        }
        
        return text;
    }

    private static string CleanArxivNoise(string text)
    {
        text = ArxivUiNoiseRegex.Replace(text, "");
        text = CiteAsSectionRegex.Replace(text, "");
        
        var lines = text.Split('\n', StringSplitOptions.RemoveEmptyEntries);
        var filteredLines = lines
            .Select(line => line.Trim())
            .Where(line => line.Length >= 30)
            .ToList();
        
        return string.Join("\n", filteredLines);
    }
}