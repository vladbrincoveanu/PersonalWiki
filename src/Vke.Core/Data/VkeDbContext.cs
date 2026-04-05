using DuckDB.NET.Data;
using Vke.Core.Data.Models;

namespace Vke.Core.Data;

public class VkeDbContext : IDisposable
{
    private readonly DuckDBConnection _connection;
    private readonly string _databasePath;

    public VkeDbContext(string databasePath)
    {
        _databasePath = databasePath;
        _connection = new DuckDBConnection($"Data Source={databasePath}");
        _connection.Open();
    }

    public void InitializeDatabase()
    {
        using var cmd = _connection.CreateCommand();
        
        cmd.CommandText = @"
            CREATE TABLE IF NOT EXISTS sources (
                id              TEXT PRIMARY KEY,
                url             TEXT NOT NULL,
                title           TEXT,
                source_type     TEXT NOT NULL,
                author          TEXT,
                publication     TEXT,
                published_at    DATE,
                fetched_at      TIMESTAMP DEFAULT now(),
                domain          TEXT,
                cites_urls      TEXT[],
                cites_source_ids TEXT[],
                is_active       BOOLEAN DEFAULT TRUE
            );

            CREATE TABLE IF NOT EXISTS claims (
                id              TEXT PRIMARY KEY,
                statement       TEXT NOT NULL,
                normalized      TEXT NOT NULL,
                source_id       TEXT NOT NULL REFERENCES sources(id),
                location        TEXT,
                domain          TEXT,
                verified        BOOLEAN DEFAULT FALSE,
                verification_score REAL,
                tier            INTEGER DEFAULT 4,
                independent_source_count INTEGER DEFAULT 0,
                first_seen      TIMESTAMP DEFAULT now(),
                last_verified   TIMESTAMP,
                stale_after     TIMESTAMP,
                is_active       BOOLEAN DEFAULT TRUE
            );

            CREATE TABLE IF NOT EXISTS edges (
                source_node     TEXT NOT NULL,
                target_node     TEXT NOT NULL,
                relation        TEXT NOT NULL,
                weight          REAL DEFAULT 1.0,
                created_at      TIMESTAMP DEFAULT now(),
                created_by      TEXT,
                evidence_source TEXT,
                PRIMARY KEY (source_node, target_node, relation)
            );

            CREATE TABLE IF NOT EXISTS source_types (
                type_key        TEXT PRIMARY KEY,
                label           TEXT NOT NULL,
                base_tier       INTEGER NOT NULL,
                max_confidence  REAL NOT NULL,
                description     TEXT,
                examples        TEXT
            );
        ";
        cmd.ExecuteNonQuery();
        
        SeedSourceTypes();
    }

    private void SeedSourceTypes()
    {
        var types = new[]
        {
            ("sec_10k", "SEC 10-K Annual Report", 1, 0.95),
            ("sec_10q", "SEC 10-Q Quarterly Report", 1, 0.90),
            ("sec_8k", "SEC 8-K Current Report", 1, 0.92),
            ("sec_proxy", "SEC Proxy Statement (DEF 14A)", 1, 0.90),
            ("peer_reviewed", "Peer-Reviewed Journal Paper", 1, 0.88),
            ("central_bank", "Central Bank Publication", 1, 0.93),
            ("preprint", "arXiv/SSRN Preprint", 2, 0.70),
            ("news_wire", "Wire Service Report", 2, 0.75),
            ("sell_side", "Sell-Side Analyst Report", 2, 0.65),
            ("data_provider", "Financial Data Provider", 2, 0.80),
            ("govt_stats", "Government Statistical Agency", 2, 0.85),
            ("news_article", "News Article / Journalism", 3, 0.55),
            ("conference_talk", "Conference Talk / Transcript", 3, 0.55),
            ("company_blog", "Company Blog / PR", 3, 0.50),
            ("industry_report", "Industry / Consulting Report", 3, 0.55),
            ("blog_post", "Personal Blog / Substack", 4, 0.30),
            ("social_media", "Social Media Post", 4, 0.20),
            ("anonymous", "Anonymous / Unknown Origin", 4, 0.10),
            ("llm_generated", "LLM-Generated Content", 4, 0.15),
        };

        foreach (var (key, label, tier, confidence) in types)
        {
            InsertSourceType(new SourceType { TypeKey = key, Label = label, BaseTier = tier, MaxConfidence = (decimal)confidence });
        }
    }

    public void InsertSource(Source source)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            INSERT INTO sources (id, url, title, source_type, author, publication, published_at, fetched_at, domain, cites_urls, cites_source_ids, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";
        cmd.Parameters.Add(new DuckDBParameter(source.Id));
        cmd.Parameters.Add(new DuckDBParameter(source.Url));
        cmd.Parameters.Add(new DuckDBParameter(source.Title));
        cmd.Parameters.Add(new DuckDBParameter(source.SourceType));
        cmd.Parameters.Add(new DuckDBParameter(source.Author));
        cmd.Parameters.Add(new DuckDBParameter(source.Publication));
        cmd.Parameters.Add(new DuckDBParameter(source.PublishedAt?.ToString("yyyy-MM-dd")));
        cmd.Parameters.Add(new DuckDBParameter(source.FetchedAt));
        cmd.Parameters.Add(new DuckDBParameter(source.Domain));
        cmd.Parameters.Add(new DuckDBParameter(source.CitesUrls.Count == 0 ? "[]" : "['" + string.Join("','", source.CitesUrls) + "']"));
        cmd.Parameters.Add(new DuckDBParameter(source.CitesSourceIds.Count == 0 ? "[]" : "['" + string.Join("','", source.CitesSourceIds) + "']"));
        cmd.Parameters.Add(new DuckDBParameter(source.IsActive));
        cmd.ExecuteNonQuery();
    }

    public Source? GetSourceById(string id)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT * FROM sources WHERE id = ?";
        cmd.Parameters.Add(new DuckDBParameter(id));
        using var reader = cmd.ExecuteReader();
        if (reader.Read())
            return MapSource(reader);
        return null;
    }

    public void InsertClaim(Claim claim)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            INSERT INTO claims (id, statement, normalized, source_id, location, domain, verified, verification_score, tier, independent_source_count, first_seen, last_verified, stale_after, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";
        cmd.Parameters.Add(new DuckDBParameter(claim.Id));
        cmd.Parameters.Add(new DuckDBParameter(claim.Statement));
        cmd.Parameters.Add(new DuckDBParameter(claim.Normalized));
        cmd.Parameters.Add(new DuckDBParameter(claim.SourceId));
        cmd.Parameters.Add(new DuckDBParameter(claim.Location));
        cmd.Parameters.Add(new DuckDBParameter(claim.Domain));
        cmd.Parameters.Add(new DuckDBParameter(claim.Verified));
        cmd.Parameters.Add(new DuckDBParameter((double)claim.VerificationScore));
        cmd.Parameters.Add(new DuckDBParameter(claim.Tier));
        cmd.Parameters.Add(new DuckDBParameter(claim.IndependentSourceCount));
        cmd.Parameters.Add(new DuckDBParameter(claim.FirstSeen));
        cmd.Parameters.Add(new DuckDBParameter(claim.LastVerified));
        cmd.Parameters.Add(new DuckDBParameter(claim.StaleAfter));
        cmd.Parameters.Add(new DuckDBParameter(claim.IsActive));
        cmd.ExecuteNonQuery();
    }

    public void InsertEdge(Edge edge)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            INSERT INTO edges (source_node, target_node, relation, weight, created_at, created_by, evidence_source)
            VALUES (?, ?, ?, ?, ?, ?, ?)";
        cmd.Parameters.Add(new DuckDBParameter(edge.SourceNode));
        cmd.Parameters.Add(new DuckDBParameter(edge.TargetNode));
        cmd.Parameters.Add(new DuckDBParameter(edge.Relation));
        cmd.Parameters.Add(new DuckDBParameter((double)edge.Weight));
        cmd.Parameters.Add(new DuckDBParameter(edge.CreatedAt));
        cmd.Parameters.Add(new DuckDBParameter(edge.CreatedBy));
        cmd.Parameters.Add(new DuckDBParameter(edge.EvidenceSource));
        cmd.ExecuteNonQuery();
    }

    public void InsertSourceType(SourceType st)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            INSERT OR IGNORE INTO source_types (type_key, label, base_tier, max_confidence, description, examples)
            VALUES (?, ?, ?, ?, ?, ?)";
        cmd.Parameters.Add(new DuckDBParameter(st.TypeKey));
        cmd.Parameters.Add(new DuckDBParameter(st.Label));
        cmd.Parameters.Add(new DuckDBParameter(st.BaseTier));
        cmd.Parameters.Add(new DuckDBParameter((double)st.MaxConfidence));
        cmd.Parameters.Add(new DuckDBParameter(st.Description));
        cmd.Parameters.Add(new DuckDBParameter(st.Examples));
        cmd.ExecuteNonQuery();
    }

    public int GetBaseTier(string sourceType)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT base_tier FROM source_types WHERE type_key = ?";
        cmd.Parameters.Add(new DuckDBParameter(sourceType));
        using var reader = cmd.ExecuteReader();
        if (reader.Read())
            return reader.GetInt32(0);
        return 4;
    }

    public IEnumerable<T> Query<T>(string sql)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = sql;
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
            yield return (T)reader.GetValue(0);
    }

    private static Source MapSource(DuckDBDataReader reader) => new()
    {
        Id = reader.GetString(0),
        Url = reader.GetString(1),
        Title = reader.IsDBNull(2) ? null : reader.GetString(2),
        SourceType = reader.GetString(3),
        Author = reader.IsDBNull(4) ? null : reader.GetString(4),
        Publication = reader.IsDBNull(5) ? null : reader.GetString(5),
        PublishedAt = reader.IsDBNull(6) ? null : (DateOnly)reader.GetValue(6),
        FetchedAt = reader.GetDateTime(7),
        Domain = reader.IsDBNull(8) ? null : reader.GetString(8),
        IsActive = reader.IsDBNull(11) || reader.GetBoolean(11),
    };

    public void Dispose()
    {
        _connection?.Close();
        _connection?.Dispose();
    }
}