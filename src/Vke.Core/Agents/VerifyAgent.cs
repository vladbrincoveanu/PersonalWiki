using Vke.Core.Data;
using Vke.Core.Data.Models;
using Vke.Core.Services;
using Vke.Core.Utils;

namespace Vke.Core.Agents;

public class VerifyAgent
{
    private readonly VkeDbContext _db;
    private readonly ILlmClient _llm;
    private const decimal VerificationThreshold = 0.5m;

    public VerifyAgent(VkeDbContext db, ILlmClient llm)
    {
        _db = db;
        _llm = llm;
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
            var score = await _llm.VerifyClaimAsync(claim.Statement, source.Url);

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
        }

        var cycles = _db.DetectCycles();
        if (cycles.Any())
            QuarantineCyclicClaims(cycles);

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
}

public class VerifyResult
{
    public int Verified { get; set; }
    public int Quarantined { get; set; }
    public int CyclesDetected { get; set; }
}