using Vke.Core.Data;
using Vke.Core.Data.Models;
using DuckDB.NET.Data;

namespace Vke.Core.Agents;

public class LintAgent
{
    private readonly VkeDbContext _db;

    public LintAgent(VkeDbContext db)
    {
        _db = db;
    }

    public List<Claim> ScanStaleClaims()
    {
        using var cmd = _db.CreateCommand();
        cmd.CommandText = "SELECT * FROM claims WHERE status IN (1, 2) AND is_active = TRUE AND stale_after < ?";
        cmd.Parameters.Add(new DuckDBParameter(DateTime.UtcNow));
        
        var claims = new List<Claim>();
        using var reader = (DuckDBDataReader)cmd.ExecuteReader();
        while (reader.Read())
            claims.Add(MapClaim(reader));
        return claims;
    }

    public List<Source> FindOrphanSources()
    {
        using var cmd = _db.CreateCommand();
        cmd.CommandText = @"
            SELECT s.* FROM sources s
            LEFT JOIN edges e ON s.id = e.source_node AND e.relation = 'source_asserts_claim'
            WHERE e.source_node IS NULL AND s.is_active = TRUE";
        
        var sources = new List<Source>();
        using var reader = (DuckDBDataReader)cmd.ExecuteReader();
        while (reader.Read())
            sources.Add(VkeDbContext.MapSource(reader));
        return sources;
    }

    public List<(string claim1, string claim2)> FindContradictions()
    {
        using var cmd = _db.CreateCommand();
        cmd.CommandText = @"
            SELECT c1.id, c2.id FROM claims c1
            JOIN claims c2 ON c1.id < c2.id
            WHERE c1.status IN (1, 2) AND c2.status IN (1, 2)
            AND c1.is_active = TRUE AND c2.is_active = TRUE
            AND c1.normalized LIKE c2.normalized || '%'
            AND c1.statement != c2.statement
            LIMIT 100";
        
        var contradictions = new List<(string, string)>();
        using var reader = (DuckDBDataReader)cmd.ExecuteReader();
        while (reader.Read())
            contradictions.Add((reader.GetString(0), reader.GetString(1)));
        return contradictions;
    }

    private static Claim MapClaim(DuckDBDataReader reader) => new()
    {
        Id = reader.GetString(0),
        Statement = reader.GetString(1),
        Normalized = reader.GetString(2),
        SourceId = reader.GetString(3),
        Location = reader.IsDBNull(4) ? null : reader.GetString(4),
        Domain = reader.IsDBNull(5) ? null : reader.GetString(5),
        Status = (VerificationStatus)reader.GetInt32(6),
        VerificationScore = reader.IsDBNull(7) ? 0 : (decimal)reader.GetFloat(7),
        WrongReason = reader.IsDBNull(8) ? null : reader.GetString(8),
        CorrectValue = reader.IsDBNull(9) ? null : reader.GetString(9),
        CorrectSource = reader.IsDBNull(10) ? null : reader.GetString(10),
        Tier = reader.GetInt32(11),
        IndependentSourceCount = reader.GetInt32(12),
        FirstSeen = reader.GetDateTime(13),
        LastVerified = reader.IsDBNull(14) ? null : reader.GetDateTime(14),
        StaleAfter = reader.IsDBNull(15) ? null : reader.GetDateTime(15),
        CorrectedAt = reader.IsDBNull(16) ? null : reader.GetDateTime(16),
        IsActive = reader.IsDBNull(17) || reader.GetBoolean(17),
    };

    public LintReport GenerateReport()
    {
        return new LintReport
        {
            StaleClaims = ScanStaleClaims(),
            OrphanSources = FindOrphanSources(),
            Contradictions = FindContradictions(),
            GeneratedAt = DateTime.UtcNow,
        };
    }
}

public class LintReport
{
    public List<Claim> StaleClaims { get; set; } = new();
    public List<Source> OrphanSources { get; set; } = new();
    public List<(string claim1, string claim2)> Contradictions { get; set; } = new();
    public DateTime GeneratedAt { get; set; }
}