using Vke.Core.Data.Models;

namespace Vke.Core.Services;

public class WikiGenerator
{
    public void GenerateEntityPage(string entityName, List<Claim> claims, string basePath)
    {
        var dir = Path.Combine(basePath, "entities");
        Directory.CreateDirectory(dir);
        
        var fileName = ToFileName(entityName) + ".md";
        var filePath = Path.Combine(dir, fileName);
        
        var md = $"# {entityName}\n\n## Verified Claims\n\n";
        
        var tier1 = claims.Where(c => c.Tier == 1).ToList();
        var tier2 = claims.Where(c => c.Tier == 2).ToList();
        var tier3 = claims.Where(c => c.Tier == 3).ToList();
        
        if (tier1.Any())
        {
            md += "### Tier 1 (Primary Sources)\n";
            foreach (var c in tier1)
                md += $"- {c.Statement} (score: {c.VerificationScore:F2})\n";
            md += "\n";
        }
        
        if (tier2.Any())
        {
            md += "### Tier 2 (Credible Secondary)\n";
            foreach (var c in tier2)
                md += $"- {c.Statement} (score: {c.VerificationScore:F2})\n";
            md += "\n";
        }
        
        if (tier3.Any())
        {
            md += "### Tier 3 (Useful but Unverified)\n";
            foreach (var c in tier3)
                md += $"- {c.Statement} (score: {c.VerificationScore:F2})\n";
            md += "\n";
        }
        
        File.WriteAllText(filePath, md);
    }

    public void GenerateSourcePage(Source source, List<Claim> claims, string basePath)
    {
        var dir = Path.Combine(basePath, "sources");
        Directory.CreateDirectory(dir);
        
        var fileName = ToFileName(source.Title ?? source.Id) + ".md";
        var filePath = Path.Combine(dir, fileName);
        
        var md = $"# {source.Title ?? source.Id}\n\n";
        md += $"- **URL:** {source.Url}\n";
        md += $"- **Type:** {source.SourceType}\n";
        md += $"- **Author:** {source.Author ?? "Unknown"}\n";
        md += $"- **Published:** {source.PublishedAt?.ToString() ?? "Unknown"}\n";
        md += $"- **Domain:** {source.Domain}\n\n";
        
        md += "## Claims\n";
        foreach (var c in claims)
            md += $"- {c.Statement} (tier: {c.Tier}, score: {c.VerificationScore:F2})\n";
        
        File.WriteAllText(filePath, md);
    }

    public void GenerateAlertsPage(
        List<string> cycles, 
        List<string> contradictions, 
        string basePath,
        List<string> pendingReviews = null,
        List<string> staleClaims = null)
    {
        var dir = Path.Combine(basePath, "alerts");
        Directory.CreateDirectory(dir);
        
        if (cycles.Any())
        {
            var cyclePath = Path.Combine(dir, "cycles.md");
            var md = "# Circular Citation Alerts\n\n";
            foreach (var cycle in cycles)
                md += $"- {cycle}\n";
            File.WriteAllText(cyclePath, md);
        }
        
        if (contradictions.Any())
        {
            var contraPath = Path.Combine(dir, "contradictions.md");
            var md = "# Contradictions Detected\n\n";
            foreach (var c in contradictions)
                md += $"- {c}\n";
            File.WriteAllText(contraPath, md);
        }

        if (pendingReviews?.Any() == true)
        {
            var pendingPath = Path.Combine(dir, "pending_reviews.md");
            var md = "# Pending Reviews\n\n";
            foreach (var id in pendingReviews)
                md += $"- {id}\n";
            File.WriteAllText(pendingPath, md);
        }

        if (staleClaims?.Any() == true)
        {
            var stalePath = Path.Combine(dir, "stale_claims.md");
            var md = "# Stale Claims\n\n";
            foreach (var id in staleClaims)
                md += $"- {id}\n";
            File.WriteAllText(stalePath, md);
        }
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