using Microsoft.Data.Sqlite;
using System.Text.Json;
using Vke.Core.Data.Models;

namespace Vke.Core.Data;

public class VkeDbContext : IDisposable
{
    private readonly SqliteConnection _connection;
    private readonly string _databasePath;

    public VkeDbContext(string databasePath)
    {
        _databasePath = databasePath;
        _connection = new SqliteConnection($"Data Source={databasePath}");
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
                fetched_at      TEXT DEFAULT (datetime('now')),
                domain          TEXT,
                cites_urls      TEXT,
                cites_source_ids TEXT,
                is_active       INTEGER DEFAULT 1,
                content         TEXT
            );

            CREATE TABLE IF NOT EXISTS claims (
                id              TEXT PRIMARY KEY,
                statement       TEXT NOT NULL,
                normalized      TEXT NOT NULL,
                source_id       TEXT NOT NULL REFERENCES sources(id),
                location        TEXT,
                domain          TEXT,
                status          INTEGER DEFAULT 0,
                verification_score REAL,
                wrong_reason    TEXT,
                correct_value   TEXT,
                correct_source  TEXT,
                tier            INTEGER DEFAULT 4,
                independent_source_count INTEGER DEFAULT 0,
                first_seen      TEXT DEFAULT (datetime('now')),
                last_verified   TEXT,
                stale_after     TEXT,
                corrected_at    TEXT,
                is_active       INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS edges (
                source_node     TEXT NOT NULL,
                target_node     TEXT NOT NULL,
                relation        TEXT NOT NULL,
                weight          REAL DEFAULT 1.0,
                created_at      TEXT DEFAULT (datetime('now')),
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

            CREATE TABLE IF NOT EXISTS raw_files (
                id              TEXT PRIMARY KEY,
                filename        TEXT NOT NULL,
                full_path       TEXT NOT NULL,
                folder          TEXT NOT NULL,
                file_type       TEXT,
                size_bytes      INTEGER,
                modified_at      TEXT,
                indexed_at      TEXT DEFAULT (datetime('now')),
                linked_entity   TEXT,
                linked_source   TEXT,
                status          TEXT NOT NULL
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
            INSERT INTO sources (id, url, title, source_type, author, publication, published_at, fetched_at, domain, cites_urls, cites_source_ids, is_active, content)
            VALUES (@p1, @p2, @p3, @p4, @p5, @p6, @p7, @p8, @p9, @p10, @p11, @p12, @p13)";
        cmd.Parameters.Add(new SqliteParameter("@p1", SqliteType.Text) { Value = source.Id ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p2", SqliteType.Text) { Value = source.Url ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p3", SqliteType.Text) { Value = source.Title ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p4", SqliteType.Text) { Value = source.SourceType ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p5", SqliteType.Text) { Value = source.Author ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p6", SqliteType.Text) { Value = source.Publication ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p7", SqliteType.Text) { Value = source.PublishedAt?.ToString("yyyy-MM-dd") ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p8", SqliteType.Text) { Value = source.FetchedAt.ToString("yyyy-MM-dd HH:mm:ss") });
        cmd.Parameters.Add(new SqliteParameter("@p9", SqliteType.Text) { Value = source.Domain ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p10", SqliteType.Text) { Value = JsonSerializer.Serialize(source.CitesUrls) });
        cmd.Parameters.Add(new SqliteParameter("@p11", SqliteType.Text) { Value = JsonSerializer.Serialize(source.CitesSourceIds) });
        cmd.Parameters.Add(new SqliteParameter("@p12", SqliteType.Integer) { Value = source.IsActive ? 1 : 0 });
        cmd.Parameters.Add(new SqliteParameter("@p13", SqliteType.Text) { Value = source.Content ?? (object)DBNull.Value });
        cmd.ExecuteNonQuery();
    }

    public string? GetSourceIdByUrl(string url)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT id FROM sources WHERE url = @url";
        cmd.Parameters.Add(new SqliteParameter("@url", SqliteType.Text) { Value = url ?? (object)DBNull.Value });
        using var reader = cmd.ExecuteReader();
        if (reader.Read())
            return reader.GetString(0);
        return null;
    }

    public Source? GetSourceById(string id)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT * FROM sources WHERE id = @id";
        cmd.Parameters.Add(new SqliteParameter("@id", SqliteType.Text) { Value = id ?? (object)DBNull.Value });
        using var reader = cmd.ExecuteReader();
        if (reader.Read())
            return MapSource(reader);
        return null;
    }

    public List<Source> GetAllSources(int limit = 20)
    {
        var sources = new List<Source>();
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = $"SELECT * FROM sources ORDER BY fetched_at DESC LIMIT {limit}";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
            sources.Add(MapSource(reader));
        return sources;
    }

    public void InsertClaim(Claim claim)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            INSERT INTO claims (id, statement, normalized, source_id, location, domain, status, verification_score, wrong_reason, correct_value, correct_source, tier, independent_source_count, first_seen, last_verified, stale_after, corrected_at, is_active)
            VALUES (@p1, @p2, @p3, @p4, @p5, @p6, @p7, @p8, @p9, @p10, @p11, @p12, @p13, @p14, @p15, @p16, @p17, @p18)";
        cmd.Parameters.Add(new SqliteParameter("@p1", SqliteType.Text) { Value = claim.Id ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p2", SqliteType.Text) { Value = claim.Statement ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p3", SqliteType.Text) { Value = claim.Normalized ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p4", SqliteType.Text) { Value = claim.SourceId ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p5", SqliteType.Text) { Value = claim.Location ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p6", SqliteType.Text) { Value = claim.Domain ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p7", SqliteType.Integer) { Value = (int)claim.Status });
        cmd.Parameters.Add(new SqliteParameter("@p8", SqliteType.Real) { Value = (double)claim.VerificationScore });
        cmd.Parameters.Add(new SqliteParameter("@p9", SqliteType.Text) { Value = claim.WrongReason ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p10", SqliteType.Text) { Value = claim.CorrectValue ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p11", SqliteType.Text) { Value = claim.CorrectSource ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p12", SqliteType.Integer) { Value = claim.Tier });
        cmd.Parameters.Add(new SqliteParameter("@p13", SqliteType.Integer) { Value = claim.IndependentSourceCount });
        cmd.Parameters.Add(new SqliteParameter("@p14", SqliteType.Text) { Value = claim.FirstSeen.ToString("yyyy-MM-dd HH:mm:ss") });
        cmd.Parameters.Add(new SqliteParameter("@p15", SqliteType.Text) { Value = claim.LastVerified?.ToString("yyyy-MM-dd HH:mm:ss") ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p16", SqliteType.Text) { Value = claim.StaleAfter?.ToString("yyyy-MM-dd HH:mm:ss") ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p17", SqliteType.Text) { Value = claim.CorrectedAt?.ToString("yyyy-MM-dd HH:mm:ss") ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p18", SqliteType.Integer) { Value = claim.IsActive ? 1 : 0 });
        cmd.ExecuteNonQuery();
    }

    public void InsertEdge(Edge edge)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            INSERT INTO edges (source_node, target_node, relation, weight, created_at, created_by, evidence_source)
            VALUES (@p1, @p2, @p3, @p4, @p5, @p6, @p7)";
        cmd.Parameters.Add(new SqliteParameter("@p1", SqliteType.Text) { Value = edge.SourceNode ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p2", SqliteType.Text) { Value = edge.TargetNode ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p3", SqliteType.Text) { Value = edge.Relation ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p4", SqliteType.Real) { Value = (double)edge.Weight });
        cmd.Parameters.Add(new SqliteParameter("@p5", SqliteType.Text) { Value = edge.CreatedAt.ToString("yyyy-MM-dd HH:mm:ss") });
        cmd.Parameters.Add(new SqliteParameter("@p6", SqliteType.Text) { Value = edge.CreatedBy ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p7", SqliteType.Text) { Value = edge.EvidenceSource ?? (object)DBNull.Value });
        cmd.ExecuteNonQuery();
    }

    public void InsertSourceType(SourceType st)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            INSERT OR IGNORE INTO source_types (type_key, label, base_tier, max_confidence, description, examples)
            VALUES (@p1, @p2, @p3, @p4, @p5, @p6)";
        cmd.Parameters.Add(new SqliteParameter("@p1", SqliteType.Text) { Value = st.TypeKey ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p2", SqliteType.Text) { Value = st.Label ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p3", SqliteType.Integer) { Value = st.BaseTier });
        cmd.Parameters.Add(new SqliteParameter("@p4", SqliteType.Real) { Value = (double)st.MaxConfidence });
        cmd.Parameters.Add(new SqliteParameter("@p5", SqliteType.Text) { Value = st.Description ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p6", SqliteType.Text) { Value = st.Examples ?? (object)DBNull.Value });
        cmd.ExecuteNonQuery();
    }

    public int GetBaseTier(string sourceType)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT base_tier FROM source_types WHERE type_key = @type";
        cmd.Parameters.Add(new SqliteParameter("@type", SqliteType.Text) { Value = sourceType ?? (object)DBNull.Value });
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

    public static Source MapSource(SqliteDataReader reader) => new()
    {
        Id = reader.GetString(0),
        Url = reader.GetString(1),
        Title = reader.IsDBNull(2) ? null : reader.GetString(2),
        SourceType = reader.GetString(3),
        Author = reader.IsDBNull(4) ? null : reader.GetString(4),
        Publication = reader.IsDBNull(5) ? null : reader.GetString(5),
        PublishedAt = reader.IsDBNull(6) ? null : DateOnly.Parse(reader.GetString(6)),
        FetchedAt = DateTime.Parse(reader.GetString(7)),
        Domain = reader.IsDBNull(8) ? null : reader.GetString(8),
        CitesUrls = reader.IsDBNull(9) ? new List<string>() : JsonSerializer.Deserialize<List<string>>(reader.GetString(9)) ?? new List<string>(),
        CitesSourceIds = reader.IsDBNull(10) ? new List<string>() : JsonSerializer.Deserialize<List<string>>(reader.GetString(10)) ?? new List<string>(),
        IsActive = reader.IsDBNull(11) || reader.GetInt32(11) == 1,
        Content = reader.IsDBNull(12) ? null : reader.GetString(12),
    };

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

    public List<string> DetectCycles()
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            WITH RECURSIVE citation_chain AS (
                SELECT 
                    source_node AS start_node,
                    target_node AS current_node,
                    source_node || ',' || target_node AS path,
                    1 AS depth,
                    target_node = source_node AS is_cycle
                FROM edges
                WHERE relation = 'source_cites_source'
                
                UNION ALL
                
                SELECT
                    cc.start_node,
                    e.target_node AS current_node,
                    cc.path || ',' || e.target_node AS path,
                    cc.depth + 1,
                    e.target_node = cc.start_node OR cc.path LIKE '%' || e.target_node || ',%' AS is_cycle
                FROM citation_chain cc
                JOIN edges e ON cc.current_node = e.source_node
                WHERE e.relation = 'source_cites_source'
                AND cc.depth < 10
                AND cc.is_cycle = 0
                AND cc.path NOT LIKE '%' || e.target_node || ',%'
            )
            SELECT DISTINCT start_node || '->' || REPLACE(path, ',', '->') AS cycle_path
            FROM citation_chain
            WHERE is_cycle = 1 OR path LIKE '%' || start_node || ',%'
            ORDER BY depth";
        
        var cycles = new List<string>();
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
            cycles.Add(reader.GetString(0));
        return cycles;
    }

    public List<string> GetRootSourcesForClaim(string claimId)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            WITH asserting_sources AS (
                SELECT source_node AS source_id
                FROM edges
                WHERE target_node = @claimId
                AND relation = 'source_asserts_claim'
            ),
            sources_citing_peers AS (
                SELECT DISTINCT e.source_node AS source_id
                FROM edges e
                WHERE e.relation = 'source_cites_source'
                AND e.source_node IN (SELECT source_id FROM asserting_sources)
                AND e.target_node IN (SELECT source_id FROM asserting_sources)
            )
            SELECT a.source_id
            FROM asserting_sources a
            WHERE a.source_id NOT IN (SELECT source_id FROM sources_citing_peers)";
        
        cmd.Parameters.Add(new SqliteParameter("@claimId", SqliteType.Text) { Value = claimId ?? (object)DBNull.Value });
        
        var roots = new List<string>();
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
            roots.Add(reader.GetString(0));
        return roots;
    }

    public void UpdateIndependenceScores(string claimId)
    {
        var roots = GetRootSourcesForClaim(claimId);
        var count = roots.Count;
        
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "UPDATE claims SET independent_source_count = @count WHERE id = @id";
        cmd.Parameters.Add(new SqliteParameter("@count", SqliteType.Integer) { Value = count });
        cmd.Parameters.Add(new SqliteParameter("@id", SqliteType.Text) { Value = claimId ?? (object)DBNull.Value });
        cmd.ExecuteNonQuery();
    }

    public Claim? GetClaimById(string id)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT * FROM claims WHERE id = @id";
        cmd.Parameters.Add(new SqliteParameter("@id", SqliteType.Text) { Value = id ?? (object)DBNull.Value });
        using var reader = cmd.ExecuteReader();
        if (reader.Read())
            return MapClaim(reader);
        return null;
    }

    public List<Claim> GetClaimsByStatus(VerificationStatus status)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT * FROM claims WHERE status = @status AND is_active = 1";
        cmd.Parameters.Add(new SqliteParameter("@status", SqliteType.Integer) { Value = (int)status });
        
        var claims = new List<Claim>();
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
            claims.Add(MapClaim(reader));
        return claims;
    }

    public List<Claim> GetStaleClaims()
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            SELECT * FROM claims 
            WHERE is_active = 1 
            AND stale_after < @now
            AND status IN (1, 2)";
        cmd.Parameters.Add(new SqliteParameter("@now", SqliteType.Text) { Value = DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss") });
        
        var claims = new List<Claim>();
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
            claims.Add(MapClaim(reader));
        return claims;
    }

    public List<(string claim1Id, string claim2Id, string statement1, string statement2, string value1, string value2)> FindContradictions()
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            SELECT c1.id, c2.id, c1.statement, c2.statement, COALESCE(c1.correct_value, c1.statement), COALESCE(c2.correct_value, c2.statement)
            FROM claims c1
            JOIN claims c2 ON c1.id < c2.id
            WHERE c1.status IN (1, 2) AND c2.status IN (1, 2)
            AND c1.is_active = 1 AND c2.is_active = 1
            AND c1.normalized = c2.normalized
            AND COALESCE(c1.correct_value, c1.statement) != COALESCE(c2.correct_value, c2.statement)
            LIMIT 100";
        
        var results = new List<(string, string, string, string, string, string)>();
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
            results.Add((reader.GetString(0), reader.GetString(1), reader.GetString(2), reader.GetString(3), reader.GetString(4), reader.GetString(5)));
        return results;
    }

    public void UpdateClaim(Claim claim)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            UPDATE claims SET
                status = @status,
                verification_score = @score,
                wrong_reason = @wrong,
                correct_value = @correct,
                correct_source = @source,
                corrected_at = @corrected,
                stale_after = @stale,
                is_active = @active
            WHERE id = @id";
        cmd.Parameters.Add(new SqliteParameter("@status", SqliteType.Integer) { Value = (int)claim.Status });
        cmd.Parameters.Add(new SqliteParameter("@score", SqliteType.Real) { Value = (double)claim.VerificationScore });
        cmd.Parameters.Add(new SqliteParameter("@wrong", SqliteType.Text) { Value = claim.WrongReason ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@correct", SqliteType.Text) { Value = claim.CorrectValue ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@source", SqliteType.Text) { Value = claim.CorrectSource ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@corrected", SqliteType.Text) { Value = claim.CorrectedAt?.ToString("yyyy-MM-dd HH:mm:ss") ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@stale", SqliteType.Text) { Value = claim.StaleAfter?.ToString("yyyy-MM-dd HH:mm:ss") ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@active", SqliteType.Integer) { Value = claim.IsActive ? 1 : 0 });
        cmd.Parameters.Add(new SqliteParameter("@id", SqliteType.Text) { Value = claim.Id ?? (object)DBNull.Value });
        cmd.ExecuteNonQuery();
    }

    public Claim? FindClaimByNormalized(string normalized)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            SELECT * FROM claims 
            WHERE normalized = @norm
            AND status IN (1, 2)
            AND is_active = 1
            ORDER BY last_verified DESC
            LIMIT 1";
        cmd.Parameters.Add(new SqliteParameter("@norm", SqliteType.Text) { Value = normalized ?? (object)DBNull.Value });
        
        using var reader = cmd.ExecuteReader();
        if (reader.Read())
            return MapClaim(reader);
        return null;
    }

    public System.Data.Common.DbCommand CreateCommand()
    {
        return _connection.CreateCommand();
    }

    public void InsertRawFile(RawFile file)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            INSERT INTO raw_files (id, filename, full_path, folder, file_type, size_bytes, modified_at, indexed_at, linked_entity, linked_source, status)
            VALUES (@p1, @p2, @p3, @p4, @p5, @p6, @p7, @p8, @p9, @p10, @p11)
            ON CONFLICT(id) DO UPDATE SET
                modified_at = excluded.modified_at,
                size_bytes = excluded.size_bytes,
                status = excluded.status
        ";
        cmd.Parameters.Add(new SqliteParameter("@p1", SqliteType.Text) { Value = file.Id ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p2", SqliteType.Text) { Value = file.Filename ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p3", SqliteType.Text) { Value = file.FullPath ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p4", SqliteType.Text) { Value = file.Folder ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p5", SqliteType.Text) { Value = file.FileType ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p6", SqliteType.Integer) { Value = file.SizeBytes ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p7", SqliteType.Text) { Value = file.ModifiedAt?.ToString("yyyy-MM-dd HH:mm:ss") ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p8", SqliteType.Text) { Value = file.IndexedAt.ToString("yyyy-MM-dd HH:mm:ss") });
        cmd.Parameters.Add(new SqliteParameter("@p9", SqliteType.Text) { Value = file.LinkedEntity ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p10", SqliteType.Text) { Value = file.LinkedSource ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@p11", SqliteType.Text) { Value = file.Status ?? (object)DBNull.Value });
        cmd.ExecuteNonQuery();
    }

    public List<RawFile> GetRawFiles(string? folder = null)
    {
        var files = new List<RawFile>();
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = folder == null
            ? "SELECT * FROM raw_files ORDER BY folder, filename"
            : "SELECT * FROM raw_files WHERE folder = @folder ORDER BY filename";
        if (folder != null)
            cmd.Parameters.Add(new SqliteParameter("@folder", SqliteType.Text) { Value = folder ?? (object)DBNull.Value });
        
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            files.Add(new RawFile
            {
                Id = reader.GetString(0),
                Filename = reader.GetString(1),
                FullPath = reader.GetString(2),
                Folder = reader.GetString(3),
                FileType = reader.IsDBNull(4) ? null : reader.GetString(4),
                SizeBytes = reader.IsDBNull(5) ? null : reader.GetInt64(5),
                ModifiedAt = reader.IsDBNull(6) ? null : DateTime.Parse(reader.GetString(6)),
                IndexedAt = DateTime.Parse(reader.GetString(7)),
                LinkedEntity = reader.IsDBNull(8) ? null : reader.GetString(8),
                LinkedSource = reader.IsDBNull(9) ? null : reader.GetString(9),
                Status = reader.GetString(10)
            });
        }
        return files;
    }

    public void UpdateRawFileStatus(string id, string status, string? linkedEntity = null, string? linkedSource = null)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            UPDATE raw_files 
            SET status = @status, linked_entity = @entity, linked_source = @source
            WHERE id = @id
        ";
        cmd.Parameters.Add(new SqliteParameter("@status", SqliteType.Text) { Value = status ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@entity", SqliteType.Text) { Value = linkedEntity ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@source", SqliteType.Text) { Value = linkedSource ?? (object)DBNull.Value });
        cmd.Parameters.Add(new SqliteParameter("@id", SqliteType.Text) { Value = id ?? (object)DBNull.Value });
        cmd.ExecuteNonQuery();
    }

    public void Dispose()
    {
        _connection?.Close();
        _connection?.Dispose();
    }
}