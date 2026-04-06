using System.Text.RegularExpressions;

namespace Vke.Core.Utils;

public static class CitationExtractor
{
    private static readonly Regex UrlPattern = new(
        @"https?://[^\s<>""']+\.htm[l]?(?=[^\s<>""']*)",
        RegexOptions.Compiled);
    
    private static readonly Regex DoiPattern = new(
        @"10\.\d{4,}/[^\s]+",
        RegexOptions.Compiled);
    
    private static readonly Regex ArxivPattern = new(
        @"arXiv:(\d+\.\d+)",
        RegexOptions.Compiled);

    public static List<string> ExtractFromSecFiling(string content)
    {
        var urls = new List<string>();
        
        urls.AddRange(UrlPattern.Matches(content)
            .Select(m => m.Value)
            .Where(u => u.Contains("sec.gov") || u.Contains("arxiv.org") || u.Contains("doi.org")));
        
        return urls.Distinct().ToList();
    }

    public static List<string> ExtractFromAcademicPaper(string content)
    {
        var urls = new List<string>();
        
        urls.AddRange(DoiPattern.Matches(content)
            .Select(m => $"https://doi.org/{m.Value}"));
        
        urls.AddRange(ArxivPattern.Matches(content)
            .Select(m => $"https://arxiv.org/abs/{m.Groups[1].Value}"));
        
        return urls.Distinct().ToList();
    }
}