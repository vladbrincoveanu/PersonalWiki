using Vke.Core.Data;
using Vke.Core.Data.Models;
using Vke.Core.Services;
using Vke.Core.Utils;

namespace Vke.Core.Agents;

public class VerifyAgent
{
    private readonly VkeDbContext _db;
    private readonly ILlmClient _llm;
    private readonly WikiGenerator _wiki;
    private readonly string _wikiPath;
    private const decimal VerificationThreshold = 0.5m;

    public VerifyAgent(VkeDbContext db, ILlmClient llm, WikiGenerator? wiki = null, string wikiPath = "vault/wiki")
    {
        _db = db;
        _llm = llm;
        _wiki = wiki ?? new WikiGenerator();
        _wikiPath = wikiPath;
    }

    public async Task<VerifyResult> VerifyAndStoreAsync(string sourceId, List<Claim> claims)
    {
        var source = _db.GetSourceById(sourceId);
        if (source == null) throw new InvalidOperationException($"Source {sourceId} not found");

        var baseTier = _db.GetBaseTier(source.SourceType);
        var verifiedClaims = new List<Claim>();
        var correctedClaims = new List<Claim>();
        var falseClaims = new List<Claim>();
        var disputedClaims = new List<Claim>();

        foreach (var claim in claims)
        {
            var (status, score, reason, correctValue, correctSource) = 
                await VerifyClaimAsync(claim, source);

            claim.Id = IdGenerator.GenerateClaimId(claim.Normalized, sourceId);
            claim.Status = status;
            claim.VerificationScore = score;
            claim.SourceId = sourceId;
            claim.Domain = source.Domain;
            claim.Tier = baseTier;
            claim.LastVerified = DateTime.UtcNow;
            claim.IndependentSourceCount = 1;

            switch (status)
            {
                case VerificationStatus.Verified:
                    claim.Tier = baseTier;
                    verifiedClaims.Add(claim);
                    break;
                    
                case VerificationStatus.Corrected:
                    claim.WrongReason = reason;
                    claim.CorrectValue = correctValue;
                    claim.CorrectSource = correctSource;
                    correctedClaims.Add(claim);
                    break;
                    
                case VerificationStatus.False:
                    claim.WrongReason = reason;
                    claim.CorrectValue = correctValue;
                    claim.CorrectSource = correctSource;
                    claim.Tier = 4;
                    falseClaims.Add(claim);
                    break;
                    
                case VerificationStatus.Disputed:
                    claim.WrongReason = reason;
                    claim.Tier = 4;
                    disputedClaims.Add(claim);
                    break;
                    
                case VerificationStatus.Unverifiable:
                    claim.WrongReason = reason;
                    claim.Tier = 4;
                    claim.StaleAfter = DateTime.UtcNow.AddDays(30);
                    break;
            }

            _db.InsertClaim(claim);
            _db.InsertEdge(new Edge
            {
                SourceNode = sourceId,
                TargetNode = claim.Id,
                Relation = "source_asserts_claim",
                CreatedBy = "verify_agent",
            });

            if (status == VerificationStatus.Verified || status == VerificationStatus.Corrected)
                _db.UpdateIndependenceScores(claim.Id);
        }

        await WriteAnnotatedRawAsync(source, claims);

        if (verifiedClaims.Any() || correctedClaims.Any())
            await WriteToWikiAsync(source, verifiedClaims, correctedClaims);

        _wiki.GenerateAlertsPage(
            cycles: _db.DetectCycles(),
            contradictions: _db.FindContradictions().Select(c => $"{c.claim1Id} vs {c.claim2Id}").ToList(),
            pendingReviews: disputedClaims.Select(c => c.Id).ToList(),
            staleClaims: _db.GetStaleClaims().Select(c => c.Id).ToList(),
            basePath: _wikiPath
        );

        return new VerifyResult
        {
            Verified = verifiedClaims.Count,
            Corrected = correctedClaims.Count,
            False = falseClaims.Count,
            Disputed = disputedClaims.Count,
        };
    }

    private async Task<(VerificationStatus status, decimal score, string? reason, string? correctValue, string? correctSource)> 
        VerifyClaimAsync(Claim claim, Source source)
    {
        var existingClaim = _db.FindClaimByNormalized(claim.Normalized);
        
        if (existingClaim != null && (existingClaim.Status == VerificationStatus.Verified || existingClaim.Status == VerificationStatus.Corrected))
        {
            var score = await _llm.VerifyClaimAsync(claim.Statement, existingClaim.Statement);
            
            if (score >= 0.8m)
                return (VerificationStatus.Verified, score, null, null, null);
            else if (score >= 0.5m)
                return (VerificationStatus.Disputed, score, "Claim contradicts established ground truth", existingClaim.CorrectValue ?? existingClaim.Statement, existingClaim.Id);
            else
                return (VerificationStatus.False, score, "Claim contradicts ground truth", existingClaim.CorrectValue ?? existingClaim.Statement, existingClaim.Id);
        }

        var sourceScore = await _llm.VerifyClaimAsync(claim.Statement, source.Content ?? source.Url);
        
        if (sourceScore >= 0.8m)
            return (VerificationStatus.Verified, sourceScore, null, null, null);
        else if (sourceScore >= 0.5m)
            return (VerificationStatus.Unverifiable, sourceScore, "Cannot confirm against source", null, null);
        else
            return (VerificationStatus.False, sourceScore, "Claim does not match source document", null, null);
    }

    private async Task WriteAnnotatedRawAsync(Source source, List<Claim> claims)
    {
        var content = source.Content ?? "";
        var falseOrDisputed = claims.Where(c => c.Status == VerificationStatus.False || c.Status == VerificationStatus.Disputed).ToList();
        
        foreach (var claim in falseOrDisputed)
        {
            var annotation = new VerificationAnnotation(
                claim.Status,
                claim.WrongReason ?? "Verification failed",
                claim.CorrectValue,
                claim.CorrectSource
            );
            content = InlineAnnotation.Annotate(content, claim.Statement, annotation);
        }

        var rawPath = Path.Combine(_wikiPath, "..", "raw", $"{source.Id}.md");
        Directory.CreateDirectory(Path.GetDirectoryName(rawPath)!);
        await File.WriteAllTextAsync(rawPath, content);

        var metaPath = Path.Combine(_wikiPath, "..", "raw", $"{source.Id}.meta.json");
        var meta = new
        {
            source.Id,
            source.Url,
            source.Title,
            source.SourceType,
            source.Author,
            source.FetchedAt,
            claims = claims.Select(c => new { c.Id, c.Statement, c.Status, c.WrongReason, c.CorrectValue })
        };
        await File.WriteAllTextAsync(metaPath, System.Text.Json.JsonSerializer.Serialize(meta, new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
    }

    private async Task WriteToWikiAsync(Source source, List<Claim> verified, List<Claim> corrected)
    {
        var allClaims = verified.Concat(corrected).ToList();
        if (!allClaims.Any()) return;

        _wiki.GenerateSourcePage(source, allClaims, _wikiPath);

        var entities = allClaims
            .SelectMany(c => ExtractEntities(c.Statement))
            .Distinct()
            .ToList();

        foreach (var entity in entities)
        {
            var entityClaims = allClaims
                .Where(c => c.Statement.Contains(entity, StringComparison.OrdinalIgnoreCase))
                .ToList();
            _wiki.GenerateEntityPage(entity, entityClaims, _wikiPath);
        }
    }

    private static List<string> ExtractEntities(string statement)
    {
        var entities = new List<string>();
        var words = statement.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var current = "";
        foreach (var word in words)
        {
            if (word.Length > 2 && char.IsUpper(word[0]))
            {
                if (!string.IsNullOrEmpty(current) && current.Length > 2)
                    entities.Add(current);
                current = word.Trim(',', '.', ':');
            }
            else
            {
                if (!string.IsNullOrEmpty(current))
                    entities.Add(current);
                current = "";
            }
        }
        if (!string.IsNullOrEmpty(current) && current.Length > 2)
            entities.Add(current);
        return entities.Distinct().ToList();
    }
}

public class VerifyResult
{
    public int Verified { get; set; }
    public int Corrected { get; set; }
    public int False { get; set; }
    public int Disputed { get; set; }
}