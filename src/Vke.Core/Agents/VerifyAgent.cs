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
        var verifiedClaims = new List<string>();
        var quarantinedClaims = new List<Claim>();

        foreach (var claim in claims)
        {
            var score = await _llm.VerifyClaimAsync(claim.Statement, source.Content ?? source.Url);

            if (score < VerificationThreshold)
            {
                quarantinedClaims.Add(claim);
                continue;
            }

            claim.Id = IdGenerator.GenerateClaimId(claim.Normalized, sourceId);
            claim.SourceId = sourceId;
            claim.Domain = source.Domain;
            claim.Verified = true;
            claim.VerificationScore = score;
            claim.Tier = baseTier;
            claim.IndependentSourceCount = 1;
            claim.StaleAfter = ComputeStaleDate(source.Domain);
            claim.LastVerified = DateTime.UtcNow;

            _db.InsertClaim(claim);

            _db.InsertEdge(new Edge
            {
                SourceNode = sourceId,
                TargetNode = claim.Id,
                Relation = "source_asserts_claim",
                CreatedBy = "verify_agent",
            });

            verifiedClaims.Add(claim.Id);
            _db.UpdateIndependenceScores(claim.Id);
        }

        var cycles = _db.DetectCycles();
        if (cycles.Any())
            QuarantineCyclicClaims(cycles);

        if (verifiedClaims.Any() && source != null)
        {
            var claimsForWiki = verifiedClaims
                .Select(id => _db.GetClaimById(id))
                .Where(c => c != null)
                .Select(c => c!)
                .ToList();
            
            _wiki.GenerateSourcePage(source, claimsForWiki, _wikiPath);
            
            var entities = claimsForWiki
                .SelectMany(c => ExtractEntities(c.Statement))
                .Distinct()
                .ToList();
            
            foreach (var entity in entities)
            {
                var entityClaims = claimsForWiki
                    .Where(c => c.Statement.Contains(entity, StringComparison.OrdinalIgnoreCase))
                    .ToList();
                _wiki.GenerateEntityPage(entity, entityClaims, _wikiPath);
            }
            
            _wiki.GenerateAlertsPage(cycles, new List<string>(), _wikiPath);
        }

        return new VerifyResult
        {
            Verified = verifiedClaims.Count,
            Quarantined = quarantinedClaims.Count,
            CyclesDetected = cycles.Count,
        };
    }

    private static DateTime ComputeStaleDate(string? domain)
    {
        return domain switch
        {
            "financial" => DateTime.UtcNow.AddDays(90),
            "academic" => DateTime.UtcNow.AddDays(365),
            _ => DateTime.UtcNow.AddDays(180),
        };
    }

        private void QuarantineCyclicClaims(List<string> cycles)
    {
        foreach (var cycle in cycles)
        {
            var nodes = cycle.Split("->");
            foreach (var node in nodes)
            {
                using var cmd = _db.CreateCommand();
                cmd.CommandText = "UPDATE claims SET tier = 4, is_active = FALSE WHERE id = ?";
                cmd.Parameters.Add(new DuckDB.NET.Data.DuckDBParameter(node));
                cmd.ExecuteNonQuery();
            }
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
    public int Quarantined { get; set; }
    public int CyclesDetected { get; set; }
}