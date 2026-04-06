using Microsoft.Data.Sqlite;
using Vke.Core.Data;
using Vke.Core.Data.Models;

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
        cmd.CommandText = "SELECT * FROM claims WHERE status IN (1, 2) AND is_active = 1 AND stale_after < @now";
        ((SqliteCommand)cmd).Parameters.Add(new SqliteParameter("@now", SqliteType.Text) { Value = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss") });
        
        var claims = new List<Claim>();
        using var reader = (SqliteDataReader)cmd.ExecuteReader();
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
            WHERE e.source_node IS NULL AND s.is_active = 1";
        
        var sources = new List<Source>();
        using var reader = (SqliteDataReader)cmd.ExecuteReader();
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
            AND c1.is_active = 1 AND c2.is_active = 1
            AND c1.normalized LIKE c2.normalized || '%'
            AND c1.statement != c2.statement
            LIMIT 100";
        
        var contradictions = new List<(string, string)>();
        using var reader = (SqliteDataReader)cmd.ExecuteReader();
        while (reader.Read())
            contradictions.Add((reader.GetString(0), reader.GetString(1)));
        return contradictions;
    }

    private static Claim MapClaim(SqliteDataReader reader) => new()
    {
        Id = reader.GetString(0),
        Statement = reader.GetString(1),
        Normalized = reader.GetString(2),
        SourceId = reader.GetString(3),
        Location = reader.IsDBNull(4) ? null : reader.GetString(4),
        Domain = reader.IsDBNull(5) ? null : reader.GetString(5),
        Status = (VerificationStatus)reader.GetInt32(6),
        VerificationScore = reader.IsDBNull(7) ? 0 : (decimal)reader.GetDouble(7),
        WrongReason = reader.IsDBNull(8) ? null : reader.GetString(8),
        CorrectValue = reader.IsDBNull(9) ? null : reader.GetString(9),
        CorrectSource = reader.IsDBNull(10) ? null : reader.GetString(10),
        Tier = reader.GetInt32(11),
        IndependentSourceCount = reader.GetInt32(12),
        FirstSeen = DateTime.Parse(reader.GetString(13)),
        LastVerified = reader.IsDBNull(14) ? null : DateTime.Parse(reader.GetString(14)),
        StaleAfter = reader.IsDBNull(15) ? null : DateTime.Parse(reader.GetString(15)),
        CorrectedAt = reader.IsDBNull(16) ? null : DateTime.Parse(reader.GetString(16)),
        IsActive = reader.IsDBNull(17) || reader.GetInt32(17) == 1,
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