using System.Text;
using Vke.Core.Data;
using Vke.Core.Data.Models;

namespace Vke.Core.Services;

public class IndexGenerator
{
    public async Task GenerateIndexAsync(string basePath, VkeDbContext db)
    {
        var indexPath = Path.Combine(basePath, "index.md");
        var sb = new StringBuilder();
        sb.AppendLine("# Research Vault Index");
        sb.AppendLine();
        sb.AppendLine($"_Last updated: {DateTime.UtcNow:yyyy-MM-dd HH:mm:ss} UTC_");
        sb.AppendLine();

        sb.AppendLine("## Entities");
        sb.AppendLine();
        var entities = GetEntitySummary(db);
        if (entities.Count > 0)
        {
            sb.AppendLine("| Entity | Tier | Claims | Last Updated |");
            sb.AppendLine("|--------|------|--------|---------------|");
            foreach (var e in entities)
                sb.AppendLine($"| [[entities/{e.Key}.md|{e.Key}]] | {e.Tier} | {e.Count} | {e.LastUpdated:yyyy-MM-dd} |");
        }
        else
        {
            sb.AppendLine("_No entities yet._");
        }
        sb.AppendLine();

        sb.AppendLine("## Sources");
        sb.AppendLine();
        var sources = GetSourceSummary(db);
        if (sources.Count > 0)
        {
            sb.AppendLine("| Source | Type | Domain | Claims |");
            sb.AppendLine("|--------|------|--------|--------|");
            foreach (var s in sources)
                sb.AppendLine($"| [[sources/{ToFileName(s.Key)}.md|{s.Key}]] | {s.Type} | {s.Domain} | {s.Count} |");
        }
        else
        {
            sb.AppendLine("_No sources yet._");
        }
        sb.AppendLine();

        sb.AppendLine("## Raw Files");
        sb.AppendLine();
        var rawFiles = db.GetRawFiles("raw");
        if (rawFiles.Count > 0)
        {
            sb.AppendLine("| File | Modified | Status |");
            sb.AppendLine("|------|----------|--------|");
            foreach (var f in rawFiles)
                sb.AppendLine($"| [[raw/{f.Filename}|{f.Filename}]] | {(f.ModifiedAt?.ToString("yyyy-MM-dd") ?? "unknown")} | {f.Status} |");
        }
        else
        {
            sb.AppendLine("_No raw files indexed._");
        }
        sb.AppendLine();

        sb.AppendLine("## Interesting");
        sb.AppendLine();
        var interesting = db.GetRawFiles("interesting");
        if (interesting.Count > 0)
        {
            sb.AppendLine("| File | Modified | Status |");
            sb.AppendLine("|------|----------|--------|");
            foreach (var f in interesting)
                sb.AppendLine($"| [[interesting/{f.Filename}|{f.Filename}]] | {(f.ModifiedAt?.ToString("yyyy-MM-dd") ?? "unknown")} | {f.Status} |");
        }
        else
        {
            sb.AppendLine("_No interesting files indexed._");
        }
        sb.AppendLine();

        sb.AppendLine("## Trusted");
        sb.AppendLine();
        var trusted = db.GetRawFiles("trusted");
        if (trusted.Count > 0)
        {
            sb.AppendLine("| File | Modified | Status |");
            sb.AppendLine("|------|----------|--------|");
            foreach (var f in trusted)
                sb.AppendLine($"| [[trusted/{f.Filename}|{f.Filename}]] | {(f.ModifiedAt?.ToString("yyyy-MM-dd") ?? "unknown")} | {f.Status} |");
        }
        else
        {
            sb.AppendLine("_No trusted files indexed._");
        }

        try
        {
            await File.WriteAllTextAsync(indexPath, sb.ToString());
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException($"Failed to write index to '{indexPath}'", ex);
        }
    }

    private List<(string Key, int Tier, int Count, DateTime LastUpdated)> GetEntitySummary(VkeDbContext db)
    {
        var summary = new List<(string, int, int, DateTime)>();
        using var cmd = db.CreateCommand();
        cmd.CommandText = @"
            SELECT c.normalized, MIN(s.source_type), COUNT(*), MAX(c.last_verified)
            FROM claims c
            JOIN sources s ON c.source_id = s.id
            WHERE c.is_active = TRUE
            GROUP BY c.normalized
            ORDER BY c.normalized
        ";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            var entity = reader.GetString(0);
            var tier = GetTierForType(reader.GetString(1));
            var count = reader.GetInt32(2);
            var lastVerified = reader.IsDBNull(3) ? DateTime.MinValue : reader.GetDateTime(3);
            summary.Add((entity, tier, count, lastVerified));
        }
        return summary;
    }

    private List<(string Key, string Type, string Domain, int Count)> GetSourceSummary(VkeDbContext db)
    {
        var summary = new List<(string, string, string, int)>();
        using var cmd = db.CreateCommand();
        cmd.CommandText = @"
            SELECT s.id, s.source_type, s.domain, COUNT(c.id)
            FROM sources s
            LEFT JOIN claims c ON s.id = c.source_id AND c.is_active = TRUE
            WHERE s.is_active = TRUE
            GROUP BY s.id, s.source_type, s.domain
            ORDER BY s.fetched_at DESC
        ";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            var id = reader.GetString(0);
            var type = reader.GetString(1);
            var domain = reader.IsDBNull(2) ? "unknown" : reader.GetString(2);
            var count = reader.GetInt32(3);
            summary.Add((id, type, domain, count));
        }
        return summary;
    }

    private int GetTierForType(string sourceType)
    {
        return sourceType switch
        {
            "sec_10k" or "sec_10q" or "sec_8k" or "sec_proxy" => 1,
            "peer_reviewed" or "central_bank" => 1,
            "preprint" or "news_wire" or "sell_side" or "data_provider" => 2,
            "govt_stats" => 2,
            "news_article" or "conference_talk" or "company_blog" or "industry_report" => 3,
            "blog_post" or "social_media" or "anonymous" or "llm_generated" => 4,
            _ => 4
        };
    }

    private static string ToFileName(string text)
    {
        return text.ToLowerInvariant()
            .Replace(" ", "-")
            .Replace(".", "")
            .Replace(",", "")
            .Replace("'", "")
            .Replace(":", "");
    }
}