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
        cmd.CommandText = "SELECT * FROM claims WHERE verified = TRUE AND is_active = TRUE AND stale_after < ?";
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
            WHERE c1.verified = TRUE AND c2.verified = TRUE
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

    private static Claim MapClaim(DuckDBDataReader reader) => new()
    {
        Id = reader.GetString(0),
        Statement = reader.GetString(1),
        Normalized = reader.GetString(2),
        SourceId = reader.GetString(3),
        Location = reader.IsDBNull(4) ? null : reader.GetString(4),
        Domain = reader.IsDBNull(5) ? null : reader.GetString(5),
        Verified = reader.GetBoolean(6),
        VerificationScore = (decimal)reader.GetFloat(7),
        Tier = reader.GetInt32(8),
        IndependentSourceCount = reader.GetInt32(9),
        FirstSeen = reader.GetDateTime(10),
        LastVerified = reader.IsDBNull(11) ? null : reader.GetDateTime(11),
        StaleAfter = reader.IsDBNull(12) ? null : reader.GetDateTime(12),
        IsActive = reader.IsDBNull(13) || reader.GetBoolean(13),
    };
}

public class LintReport
{
    public List<Claim> StaleClaims { get; set; } = new();
    public List<Source> OrphanSources { get; set; } = new();
    public List<(string claim1, string claim2)> Contradictions { get; set; } = new();
    public DateTime GeneratedAt { get; set; }
}