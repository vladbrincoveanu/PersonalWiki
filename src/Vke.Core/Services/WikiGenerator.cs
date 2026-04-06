using Vke.Core.Data.Models;

namespace Vke.Core.Services;

public class WikiGenerator
{
    public async Task GenerateEntityPage(string entityName, List<Claim> claims, string basePath, bool saveHistory = false)
    {
        var dir = Path.Combine(basePath, "entities");
        Directory.CreateDirectory(dir);
        
        var fileName = ToFileName(entityName) + ".md";
        var filePath = Path.Combine(dir, fileName);
        
        var md = $"# {entityName}\n\n";
        md += $"_Last updated: {DateTime.UtcNow:yyyy-MM-dd HH:mm:ss} UTC_\n\n";
        
        var verified = claims.Where(c => c.Status == VerificationStatus.Verified).ToList();
        var corrected = claims.Where(c => c.Status == VerificationStatus.Corrected).ToList();
        var disputed = claims.Where(c => c.Status == VerificationStatus.Disputed).ToList();
        var falseClaims = claims.Where(c => c.Status == VerificationStatus.False).ToList();
        
        if (verified.Any())
        {
            md += "## Verified Claims\n";
            foreach (var c in verified)
                md += $"- {c.Statement} [score: {c.VerificationScore:F2}]\n";
            md += "\n";
        }
        
        if (corrected.Any())
        {
            md += "## Corrected Claims\n";
            foreach (var c in corrected)
            {
                md += $"- ~~{c.Statement}~~ [CORRECTED to: {c.CorrectValue}]\n";
                md += $"  - Reason: {c.WrongReason}\n";
                md += $"  - Corrected by: {c.CorrectSource}\n";
            }
            md += "\n";
        }
        
        if (disputed.Any())
        {
            md += "## Disputed Claims\n";
            foreach (var c in disputed)
            {
                md += $"- {c.Statement} [DISPUTED]\n";
                md += $"  - Reason: {c.WrongReason}\n";
            }
            md += "\n";
        }
        
        if (falseClaims.Any())
        {
            md += "## False Claims (Rejected)\n";
            foreach (var c in falseClaims)
            {
                md += $"- ~~{c.Statement}~~ [FALSE]\n";
                md += $"  - Reason: {c.WrongReason}\n";
                if (!string.IsNullOrEmpty(c.CorrectValue))
                    md += $"  - Correct value: {c.CorrectValue}\n";
            }
            md += "\n";
        }
        
        await File.WriteAllTextAsync(filePath, md);
        
        if (saveHistory)
        {
            var historyDir = Path.Combine(dir, ToFileName(entityName));
            Directory.CreateDirectory(historyDir);
            var historyFile = Path.Combine(historyDir, $"{DateTime.UtcNow:yyyy-MM-dd}.md");
            await File.WriteAllTextAsync(historyFile, md);
        }
    }

    public async Task GenerateSourcePage(Source source, List<Claim> claims, string basePath)
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
        md += $"- **Domain:** {source.Domain}\n";
        md += $"- **Fetched:** {source.FetchedAt:yyyy-MM-dd HH:mm:ss}\n\n";
        
        md += "## Claims\n\n";
        
        var verified = claims.Where(c => c.Status == VerificationStatus.Verified).ToList();
        var corrected = claims.Where(c => c.Status == VerificationStatus.Corrected).ToList();
        var falseClaims = claims.Where(c => c.Status == VerificationStatus.False).ToList();
        
        if (verified.Any())
        {
            md += "### Verified\n";
            foreach (var c in verified)
                md += $"- {c.Statement} (tier: {c.Tier}, score: {c.VerificationScore:F2})\n";
        }
        
        if (corrected.Any())
        {
            md += "### Corrected\n";
            foreach (var c in corrected)
                md += $"- ~~{c.Statement}~~ → {c.CorrectValue} (source: {c.CorrectSource})\n";
        }
        
        if (falseClaims.Any())
        {
            md += "### False/Rejected\n";
            foreach (var c in falseClaims)
                md += $"- ~~{c.Statement}~~ [reason: {c.WrongReason}]\n";
        }
        
        await File.WriteAllTextAsync(filePath, md);
    }

    public async Task GenerateAlertsPage(List<string> cycles, List<string> contradictions, string basePath, List<string>? pendingReviews = null, List<string>? staleClaims = null)
    {
        var dir = Path.Combine(basePath, "alerts");
        Directory.CreateDirectory(dir);
        
        if (pendingReviews?.Any() == true)
        {
            var reviewPath = Path.Combine(dir, "pending-reviews.md");
            var md = "# Claims Pending Human Review\n\n";
            md += "_Last updated: " + DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss") + "_\n\n";
            foreach (var claimId in pendingReviews)
                md += $"- Claim `{claimId}` requires human review\n";
            await File.WriteAllTextAsync(reviewPath, md);
        }
        
        if (staleClaims?.Any() == true)
        {
            var stalePath = Path.Combine(dir, "stale-claims.md");
            var md = "# Stale Claims (Need Re-verification)\n\n";
            md += "_Last updated: " + DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss") + "_\n\n";
            foreach (var claimId in staleClaims)
                md += $"- Claim `{claimId}` is stale and should be re-verified\n";
            await File.WriteAllTextAsync(stalePath, md);
        }
        
        if (cycles.Any())
        {
            var cyclePath = Path.Combine(dir, "cycles.md");
            var md = "# Circular Citation Alerts\n\n";
            foreach (var cycle in cycles)
                md += $"- {cycle}\n";
            await File.WriteAllTextAsync(cyclePath, md);
        }
        
        if (contradictions.Any())
        {
            var contraPath = Path.Combine(dir, "contradictions.md");
            var md = "# Contradictions Detected\n\n";
            foreach (var c in contradictions)
                md += $"- {c}\n";
            await File.WriteAllTextAsync(contraPath, md);
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