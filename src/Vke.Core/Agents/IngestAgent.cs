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
    private readonly GenericUrlClient? _genericUrl;

    public IngestAgent(VkeDbContext db, ILlmClient llm, SecEdgarClient? secEdgar, SemanticScholarClient? semanticScholar, GenericUrlClient? genericUrl)
    {
        _db = db;
        _llm = llm;
        _secEdgar = secEdgar;
        _semanticScholar = semanticScholar;
        _genericUrl = genericUrl;
    }

    public async Task<(string sourceId, List<Claim> claims)> IngestAsync(string url, string sourceType, string domain)
    {
        Console.WriteLine($"[IngestAgent] IngestAsync START url={url} type={sourceType} domain={domain}");
        
        var (content, title, author, publishedAt, citesUrls) = await FetchContentAsync(url, sourceType);
        Console.WriteLine($"[IngestAgent] FetchContentAsync DONE contentLen={content.Length} title={title}");
        
        var sourceId = IdGenerator.GenerateSourceId(url, publishedAt);
        Console.WriteLine($"[IngestAgent] Generated sourceId={sourceId}");
        
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
            Content = content,
        };
        
        Console.WriteLine($"[IngestAgent] About to insert source...");
        _db.InsertSource(source);
        Console.WriteLine($"[IngestAgent] Source inserted");
        
        await ResolveCitationsAsync(sourceId, citesUrls);
        Console.WriteLine($"[IngestAgent] Citations resolved, about to extract claims...");
        
        var claims = await _llm.ExtractClaimsAsync(content, sourceType);
        Console.WriteLine($"[IngestAgent] ExtractClaimsAsync DONE, found {claims.Count} claims");
        
        foreach (var claim in claims)
        {
            claim.SourceId = sourceId;
            claim.Domain = domain;
        }
        
        Console.WriteLine($"[IngestAgent] IngestAsync END sourceId={sourceId}");
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
        else if (_genericUrl != null)
        {
            var (content, title, author, publishedAt) = await _genericUrl.FetchAsync(url);
            return (content, title, author, publishedAt, new List<string>());
        }

        throw new NotSupportedException($"Source type {sourceType} not supported");
    }

    private async Task ResolveCitationsAsync(string sourceId, List<string> citesUrls)
    {
        foreach (var citedUrl in citesUrls)
        {
            var existingId = _db.GetSourceIdByUrl(citedUrl);
            
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