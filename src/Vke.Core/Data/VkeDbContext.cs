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
                is_active       BOOLEAN DEFAULT TRUE,
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
                first_seen      TIMESTAMP DEFAULT now(),
                last_verified   TIMESTAMP,
                stale_after     TIMESTAMP,
                corrected_at    TIMESTAMP,
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

            CREATE TABLE IF NOT EXISTS raw_files (
                id              TEXT PRIMARY KEY,
                filename        TEXT NOT NULL,
                full_path       TEXT NOT NULL,
                folder          TEXT NOT NULL,
                file_type       TEXT,
                size_bytes      BIGINT,
                modified_at     TIMESTAMP,
                indexed_at      TIMESTAMP DEFAULT now(),
                linked_entity   TEXT,
                linked_source   TEXT,
                status          TEXT DEFAULT 'pending'
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";
        cmd.Parameters.Add(new DuckDBParameter(source.Id));
        cmd.Parameters.Add(new DuckDBParameter(source.Url));
        cmd.Parameters.Add(new DuckDBParameter(source.Title));
        cmd.Parameters.Add(new DuckDBParameter(source.SourceType));
        cmd.Parameters.Add(new DuckDBParameter(source.Author));
        cmd.Parameters.Add(new DuckDBParameter(source.Publication));
        cmd.Parameters.Add(new DuckDBParameter(source.PublishedAt?.ToString("yyyy-MM-dd")));
        cmd.Parameters.Add(new DuckDBParameter(source.FetchedAt));
        cmd.Parameters.Add(new DuckDBParameter(source.Domain));
        cmd.Parameters.Add(new DuckDBParameter(source.CitesUrls.Count == 0 ? "[]" : "['" + string.Join("','", source.CitesUrls.Select(s => s.Replace("'", "''"))) + "']"));
        cmd.Parameters.Add(new DuckDBParameter(source.CitesSourceIds.Count == 0 ? "[]" : "['" + string.Join("','", source.CitesSourceIds.Select(s => s.Replace("'", "''"))) + "']"));
        cmd.Parameters.Add(new DuckDBParameter(source.IsActive));
        cmd.Parameters.Add(new DuckDBParameter(source.Content));
        cmd.ExecuteNonQuery();
    }

    public string? GetSourceIdByUrl(string url)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT id FROM sources WHERE url = ?";
        cmd.Parameters.Add(new DuckDBParameter(url));
        using var reader = cmd.ExecuteReader();
        if (reader.Read())
            return reader.GetString(0);
        return null;
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
            INSERT INTO claims (id, statement, normalized, source_id, location, domain, status, verification_score, wrong_reason, correct_value, correct_source, tier, independent_source_count, first_seen, last_verified, stale_after, corrected_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";
        cmd.Parameters.Add(new DuckDBParameter(claim.Id));
        cmd.Parameters.Add(new DuckDBParameter(claim.Statement));
        cmd.Parameters.Add(new DuckDBParameter(claim.Normalized));
        cmd.Parameters.Add(new DuckDBParameter(claim.SourceId));
        cmd.Parameters.Add(new DuckDBParameter(claim.Location));
        cmd.Parameters.Add(new DuckDBParameter(claim.Domain));
        cmd.Parameters.Add(new DuckDBParameter((int)claim.Status));
        cmd.Parameters.Add(new DuckDBParameter((double)claim.VerificationScore));
        cmd.Parameters.Add(new DuckDBParameter(claim.WrongReason));
        cmd.Parameters.Add(new DuckDBParameter(claim.CorrectValue));
        cmd.Parameters.Add(new DuckDBParameter(claim.CorrectSource));
        cmd.Parameters.Add(new DuckDBParameter(claim.Tier));
        cmd.Parameters.Add(new DuckDBParameter(claim.IndependentSourceCount));
        cmd.Parameters.Add(new DuckDBParameter(claim.FirstSeen));
        cmd.Parameters.Add(new DuckDBParameter(claim.LastVerified));
        cmd.Parameters.Add(new DuckDBParameter(claim.StaleAfter));
        cmd.Parameters.Add(new DuckDBParameter(claim.CorrectedAt));
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

    public static Source MapSource(DuckDBDataReader reader) => new()
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
        Content = reader.IsDBNull(12) ? null : reader.GetString(12),
    };

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
                AND cc.is_cycle = FALSE
                AND cc.path NOT LIKE '%' || e.target_node || ',%'
            )
            SELECT DISTINCT start_node || '->' || REPLACE(path, ',', '->') AS cycle_path
            FROM citation_chain
            WHERE is_cycle = TRUE OR path LIKE '%' || start_node || ',%'
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
                WHERE target_node = ?
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
        
        cmd.Parameters.Add(new DuckDBParameter(claimId));
        
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
        cmd.CommandText = "UPDATE claims SET independent_source_count = ? WHERE id = ?";
        cmd.Parameters.Add(new DuckDBParameter(count));
        cmd.Parameters.Add(new DuckDBParameter(claimId));
        cmd.ExecuteNonQuery();
    }

    public Claim? GetClaimById(string id)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT * FROM claims WHERE id = ?";
        cmd.Parameters.Add(new DuckDBParameter(id));
        using var reader = cmd.ExecuteReader();
        if (reader.Read())
            return MapClaim(reader);
        return null;
    }

    public List<Claim> GetClaimsByStatus(VerificationStatus status)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = "SELECT * FROM claims WHERE status = ? AND is_active = TRUE";
        cmd.Parameters.Add(new DuckDBParameter((int)status));
        
        var claims = new List<Claim>();
        using var reader = (DuckDBDataReader)cmd.ExecuteReader();
        while (reader.Read())
            claims.Add(MapClaim(reader));
        return claims;
    }

    public List<Claim> GetStaleClaims()
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            SELECT * FROM claims 
            WHERE is_active = TRUE 
            AND stale_after < ?
            AND status IN (1, 2)";
        cmd.Parameters.Add(new DuckDBParameter(DateTime.UtcNow));
        
        var claims = new List<Claim>();
        using var reader = (DuckDBDataReader)cmd.ExecuteReader();
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
            AND c1.is_active = TRUE AND c2.is_active = TRUE
            AND c1.normalized = c2.normalized
            AND COALESCE(c1.correct_value, c1.statement) != COALESCE(c2.correct_value, c2.statement)
            LIMIT 100";
        
        var results = new List<(string, string, string, string, string, string)>();
        using var reader = (DuckDBDataReader)cmd.ExecuteReader();
        while (reader.Read())
            results.Add((reader.GetString(0), reader.GetString(1), reader.GetString(2), reader.GetString(3), reader.GetString(4), reader.GetString(5)));
        return results;
    }

    public void UpdateClaim(Claim claim)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            UPDATE claims SET
                status = ?,
                verification_score = ?,
                wrong_reason = ?,
                correct_value = ?,
                correct_source = ?,
                corrected_at = ?,
                stale_after = ?,
                is_active = ?
            WHERE id = ?";
        cmd.Parameters.Add(new DuckDBParameter((int)claim.Status));
        cmd.Parameters.Add(new DuckDBParameter((double)claim.VerificationScore));
        cmd.Parameters.Add(new DuckDBParameter(claim.WrongReason));
        cmd.Parameters.Add(new DuckDBParameter(claim.CorrectValue));
        cmd.Parameters.Add(new DuckDBParameter(claim.CorrectSource));
        cmd.Parameters.Add(new DuckDBParameter(claim.CorrectedAt));
        cmd.Parameters.Add(new DuckDBParameter(claim.StaleAfter));
        cmd.Parameters.Add(new DuckDBParameter(claim.IsActive));
        cmd.Parameters.Add(new DuckDBParameter(claim.Id));
        cmd.ExecuteNonQuery();
    }

    public Claim? FindClaimByNormalized(string normalized)
    {
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = @"
            SELECT * FROM claims 
            WHERE normalized = ? 
            AND status IN (1, 2)
            AND is_active = TRUE
            ORDER BY last_verified DESC
            LIMIT 1";
        cmd.Parameters.Add(new DuckDBParameter(normalized));
        
        using var reader = (DuckDBDataReader)cmd.ExecuteReader();
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                modified_at = excluded.modified_at,
                size_bytes = excluded.size_bytes,
                status = excluded.status
        ";
        cmd.Parameters.Add(new DuckDBParameter(file.Id));
        cmd.Parameters.Add(new DuckDBParameter(file.Filename));
        cmd.Parameters.Add(new DuckDBParameter(file.FullPath));
        cmd.Parameters.Add(new DuckDBParameter(file.Folder));
        cmd.Parameters.Add(new DuckDBParameter(file.FileType ?? (object)DBNull.Value));
        cmd.Parameters.Add(new DuckDBParameter(file.SizeBytes));
        cmd.Parameters.Add(new DuckDBParameter(file.ModifiedAt));
        cmd.Parameters.Add(new DuckDBParameter(file.IndexedAt));
        cmd.Parameters.Add(new DuckDBParameter(file.LinkedEntity ?? (object)DBNull.Value));
        cmd.Parameters.Add(new DuckDBParameter(file.LinkedSource ?? (object)DBNull.Value));
        cmd.Parameters.Add(new DuckDBParameter(file.Status));
        cmd.ExecuteNonQuery();
    }

    public List<RawFile> GetRawFiles(string? folder = null)
    {
        var files = new List<RawFile>();
        using var cmd = _connection.CreateCommand();
        cmd.CommandText = folder == null
            ? "SELECT * FROM raw_files ORDER BY folder, filename"
            : "SELECT * FROM raw_files WHERE folder = ? ORDER BY filename";
        if (folder != null)
            cmd.Parameters.Add(new DuckDBParameter(folder));
        
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
                ModifiedAt = reader.IsDBNull(6) ? null : reader.GetDateTime(6),
                IndexedAt = reader.GetDateTime(7),
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
            SET status = ?, linked_entity = ?, linked_source = ?
            WHERE id = ?
        ";
        cmd.Parameters.Add(new DuckDBParameter(status));
        cmd.Parameters.Add(new DuckDBParameter(linkedEntity ?? (object)DBNull.Value));
        cmd.Parameters.Add(new DuckDBParameter(linkedSource ?? (object)DBNull.Value));
        cmd.Parameters.Add(new DuckDBParameter(id));
        cmd.ExecuteNonQuery();
    }

    public void Dispose()
    {
        _connection?.Close();
        _connection?.Dispose();
    }
}