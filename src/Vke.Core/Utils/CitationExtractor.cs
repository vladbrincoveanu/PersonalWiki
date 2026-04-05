using System.Text.RegularExpressions;

namespace Vke.Core.Utils;

public static class CitationExtractor
{
    public static List<string> ExtractFromSecFiling(string content)
    {
        var urls = new List<string>();
        
        var urlPattern = @"https?://[^\s<>""']+\.htm[l]?(?=[^\s<>""']*)";
        urls.AddRange(Regex.Matches(content, urlPattern)
            .Select(m => m.Value)
            .Where(u => u.Contains("sec.gov") || u.Contains("arxiv.org") || u.Contains("doi.org")));
        
        return urls.Distinct().ToList();
    }

    public static List<string> ExtractFromAcademicPaper(string content)
    {
        var urls = new List<string>();
        
        var doiPattern = @"10\.\d{4,}/[^\s]+";
        urls.AddRange(Regex.Matches(content, doiPattern)
            .Select(m => $"https://doi.org/{m.Value}"));
        
        var arxivPattern = @"arXiv:(\d+\.\d+)";
        urls.AddRange(Regex.Matches(content, arxivPattern)
            .Select(m => $"https://arxiv.org/abs/{m.Groups[1].Value}"));
        
        return urls.Distinct().ToList();
    }
}