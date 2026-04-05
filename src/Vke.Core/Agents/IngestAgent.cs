using Vke.Core.Data;
using Vke.Core.Data.Models;
using Vke.Core.Services;
using Vke.Core.Utils;

namespace Vke.Core.Agents;

public class IngestAgent
{
    private readonly VkeDbContext _db;
    private readonly ILlmClient _llm;
    private readonly SecEdgarClient? _secEdgar;
    private readonly SemanticScholarClient? _semanticScholar;

    public IngestAgent(VkeDbContext db, ILlmClient llm, SecEdgarClient? secEdgar, SemanticScholarClient? semanticScholar)
    {
        _db = db;
        _llm = llm;
        _secEdgar = secEdgar;
        _semanticScholar = semanticScholar;
    }

    public async Task<(string sourceId, List<Claim> claims)> IngestAsync(string url, string sourceType, string domain)
    {
        var (content, title, author, publishedAt, citesUrls) = await FetchContentAsync(url, sourceType);
        
        var sourceId = IdGenerator.GenerateSourceId(url, publishedAt);
        var source = new Source
        {
            Id = sourceId,
            Url = url,
            Title = title,
            SourceType = sourceType,
            Author = author,
            PublishedAt = publishedAt,
            Domain = domain,
            CitesUrls = citesUrls,
            FetchedAt = DateTime.UtcNow,
        };
        
        _db.InsertSource(source);
        await ResolveCitationsAsync(sourceId, citesUrls);
        
        var claims = await _llm.ExtractClaimsAsync(content, sourceType);
        foreach (var claim in claims)
        {
            claim.SourceId = sourceId;
            claim.Domain = domain;
        }
        
        return (sourceId, claims);
    }

    private async Task<(string content, string? title, string? author, DateOnly? publishedAt, List<string> citesUrls)> FetchContentAsync(string url, string sourceType)
    {
        if (sourceType.StartsWith("sec_"))
        {
            if (_secEdgar == null) throw new InvalidOperationException("SEC EDGAR client not configured");
            var content = await _secEdgar.FetchFilingContentAsync(url);
            var citesUrls = CitationExtractor.ExtractFromSecFiling(content);
            return (content, null, null, null, citesUrls);
        }
        else if (sourceType == "preprint" || sourceType == "peer_reviewed")
        {
            if (_semanticScholar == null) throw new InvalidOperationException("Semantic Scholar client not configured");
            var doi = ExtractArxivDoi(url);
            var paper = await _semanticScholar.GetPaperAsync(doi);
            var citesUrls = paper.References.Select(r => r.PaperId ?? "").Where(s => !string.IsNullOrEmpty(s)).ToList();
            return (paper.Abstract ?? "", paper.Title, paper.Authors.FirstOrDefault()?.Name, null, citesUrls);
        }
        
        throw new NotSupportedException($"Source type {sourceType} not supported");
    }

    private async Task ResolveCitationsAsync(string sourceId, List<string> citesUrls)
    {
        foreach (var citedUrl in citesUrls)
        {
            var existingSources = _db.Query<string>($"SELECT id FROM sources WHERE url = '{citedUrl.Replace("'", "''")}'");
            var existingId = existingSources.FirstOrDefault();
            
            if (!string.IsNullOrEmpty(existingId))
            {
                _db.InsertEdge(new Edge
                {
                    SourceNode = sourceId,
                    TargetNode = existingId,
                    Relation = "source_cites_source",
                    CreatedBy = "ingest_agent",
                });
            }
        }
    }

    private static string ExtractArxivDoi(string url)
    {
        var match = System.Text.RegularExpressions.Regex.Match(url, @"arxiv\.org/abs/(\d+\.\d+)");
        if (match.Success)
            return $"10.48550/arXiv.{match.Groups[1].Value}";
        return url;
    }
}