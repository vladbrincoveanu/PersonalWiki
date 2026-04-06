using System.Text;
using Vke.Core.Data.Models;
using Vke.Core.Utils;

namespace Vke.Core.Services;

public class WikiGenerator
{
    public async Task GenerateEntityPage(string entityName, List<Claim> claims, string basePath, bool saveHistory = false)
    {
        var dir = Path.Combine(basePath, "entities");
        Directory.CreateDirectory(dir);
        
        var fileName = StringUtils.ToFileName(entityName) + ".md";
        var filePath = Path.Combine(dir, fileName);
        
        var sb = new StringBuilder();
        sb.AppendLine($"# {entityName}");
        sb.AppendLine();
        sb.AppendLine($"_Last updated: {DateTime.UtcNow:yyyy-MM-dd HH:mm:ss} UTC_");
        sb.AppendLine();
        
        var verified = claims.Where(c => c.Status == VerificationStatus.Verified).ToList();
        var corrected = claims.Where(c => c.Status == VerificationStatus.Corrected).ToList();
        var disputed = claims.Where(c => c.Status == VerificationStatus.Disputed).ToList();
        var falseClaims = claims.Where(c => c.Status == VerificationStatus.False).ToList();
        
        if (verified.Count > 0)
        {
            sb.AppendLine("## Verified Claims");
            foreach (var c in verified)
                sb.AppendLine($"- {c.Statement} [score: {c.VerificationScore:F2}]");
            sb.AppendLine();
        }
        
        if (corrected.Count > 0)
        {
            sb.AppendLine("## Corrected Claims");
            foreach (var c in corrected)
            {
                sb.AppendLine($"- ~~{c.Statement}~~ [CORRECTED to: {c.CorrectValue}]");
                sb.AppendLine($"  - Reason: {c.WrongReason}");
                sb.AppendLine($"  - Corrected by: {c.CorrectSource}");
            }
            sb.AppendLine();
        }
        
        if (disputed.Count > 0)
        {
            sb.AppendLine("## Disputed Claims");
            foreach (var c in disputed)
            {
                sb.AppendLine($"- {c.Statement} [DISPUTED]");
                sb.AppendLine($"  - Reason: {c.WrongReason}");
            }
            sb.AppendLine();
        }
        
        if (falseClaims.Count > 0)
        {
            sb.AppendLine("## False Claims (Rejected)");
            foreach (var c in falseClaims)
            {
                sb.AppendLine($"- ~~{c.Statement}~~ [FALSE]");
                sb.AppendLine($"  - Reason: {c.WrongReason}");
                if (!string.IsNullOrEmpty(c.CorrectValue))
                    sb.AppendLine($"  - Correct value: {c.CorrectValue}");
            }
            sb.AppendLine();
        }
        
        var sourceIds = claims.Where(c => !string.IsNullOrEmpty(c.SourceId)).Select(c => c.SourceId).Distinct().ToList();
        if (sourceIds.Count > 0)
        {
            sb.AppendLine("## Sources");
            foreach (var sourceId in sourceIds)
                sb.AppendLine($"- [[sources/{StringUtils.ToFileName(sourceId)}.md|Source {sourceId}]]");
            sb.AppendLine();
        }
        
        var md = sb.ToString();
        try
        {
            await File.WriteAllTextAsync(filePath, md);
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException($"Failed to write entity page for '{entityName}' to '{filePath}'", ex);
        }
        
        if (saveHistory)
        {
            var historyDir = Path.Combine(dir, StringUtils.ToFileName(entityName));
            Directory.CreateDirectory(historyDir);
            var historyFile = Path.Combine(historyDir, $"{DateTime.UtcNow:yyyy-MM-dd}.md");
            try
            {
                await File.WriteAllTextAsync(historyFile, md);
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException($"Failed to write history page for '{entityName}' to '{historyFile}'", ex);
            }
        }
    }

    public async Task GenerateSourcePage(Source source, List<Claim> claims, string basePath)
    {
        var dir = Path.Combine(basePath, "sources");
        Directory.CreateDirectory(dir);
        
        var fileName = StringUtils.ToFileName(source.Title ?? source.Id) + ".md";
        var filePath = Path.Combine(dir, fileName);
        
        var sb = new StringBuilder();
        sb.AppendLine($"# {source.Title ?? source.Id}");
        sb.AppendLine();
        sb.AppendLine($"- **URL:** {source.Url}");
        sb.AppendLine($"- **Type:** {source.SourceType}");
        sb.AppendLine($"- **Author:** {source.Author ?? "Unknown"}");
        sb.AppendLine($"- **Published:** {source.PublishedAt?.ToString() ?? "Unknown"}");
        sb.AppendLine($"- **Domain:** {source.Domain}");
        sb.AppendLine($"- **Fetched:** {source.FetchedAt:yyyy-MM-dd HH:mm:ss}");
        sb.AppendLine();
        sb.AppendLine("## Claims");
        sb.AppendLine();
        
        var verified = claims.Where(c => c.Status == VerificationStatus.Verified).ToList();
        var corrected = claims.Where(c => c.Status == VerificationStatus.Corrected).ToList();
        var falseClaims = claims.Where(c => c.Status == VerificationStatus.False).ToList();
        
        if (verified.Count > 0)
        {
            sb.AppendLine("### Verified");
            foreach (var c in verified)
                sb.AppendLine($"- {c.Statement} (tier: {c.Tier}, score: {c.VerificationScore:F2})");
        }
        
        if (corrected.Count > 0)
        {
            sb.AppendLine("### Corrected");
            foreach (var c in corrected)
                sb.AppendLine($"- ~~{c.Statement}~~ → {c.CorrectValue} (source: {c.CorrectSource})");
        }
        
        if (falseClaims.Count > 0)
        {
            sb.AppendLine("### False/Rejected");
            foreach (var c in falseClaims)
                sb.AppendLine($"- ~~{c.Statement}~~ [reason: {c.WrongReason}]");
        }
        
        var entityNames = claims.Select(c => c.Normalized?.Split(':')[0] ?? "").Where(s => !string.IsNullOrEmpty(s)).Distinct().ToList();
        if (entityNames.Count > 0)
        {
            sb.AppendLine("## Entities");
            foreach (var entity in entityNames)
                sb.AppendLine($"- [[entities/{StringUtils.ToFileName(entity)}.md|{entity}]]");
            sb.AppendLine();
        }
        
        try
        {
            await File.WriteAllTextAsync(filePath, sb.ToString());
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException($"Failed to write source page for '{source.Title ?? source.Id}' to '{filePath}'", ex);
        }
    }

    public async Task GenerateAlertsPage(List<string> cycles, List<string> contradictions, string basePath, List<string>? pendingReviews = null, List<string>? staleClaims = null)
    {
        var dir = Path.Combine(basePath, "alerts");
        Directory.CreateDirectory(dir);
        
        if (pendingReviews?.Any() == true)
        {
            var reviewPath = Path.Combine(dir, "pending-reviews.md");
            var sb = new StringBuilder();
            sb.AppendLine("# Claims Pending Human Review");
            sb.AppendLine();
            sb.AppendLine($"_Last updated: {DateTime.UtcNow:yyyy-MM-dd HH:mm:ss}_");
            sb.AppendLine();
            foreach (var claimId in pendingReviews)
                sb.AppendLine($"- Claim `{claimId}` requires human review");
            try
            {
                await File.WriteAllTextAsync(reviewPath, sb.ToString());
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException($"Failed to write pending reviews page to '{reviewPath}'", ex);
            }
        }
        
        if (staleClaims?.Any() == true)
        {
            var stalePath = Path.Combine(dir, "stale-claims.md");
            var sb = new StringBuilder();
            sb.AppendLine("# Stale Claims (Need Re-verification)");
            sb.AppendLine();
            sb.AppendLine($"_Last updated: {DateTime.UtcNow:yyyy-MM-dd HH:mm:ss}_");
            sb.AppendLine();
            foreach (var claimId in staleClaims)
                sb.AppendLine($"- Claim `{claimId}` is stale and should be re-verified");
            try
            {
                await File.WriteAllTextAsync(stalePath, sb.ToString());
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException($"Failed to write stale claims page to '{stalePath}'", ex);
            }
        }
        
        if (cycles.Any())
        {
            var cyclePath = Path.Combine(dir, "cycles.md");
            var sb = new StringBuilder();
            sb.AppendLine("# Circular Citation Alerts");
            sb.AppendLine();
            foreach (var cycle in cycles)
                sb.AppendLine($"- {cycle}");
            try
            {
                await File.WriteAllTextAsync(cyclePath, sb.ToString());
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException($"Failed to write cycles page to '{cyclePath}'", ex);
            }
        }
        
        if (contradictions.Any())
        {
            var contraPath = Path.Combine(dir, "contradictions.md");
            var sb = new StringBuilder();
            sb.AppendLine("# Contradictions Detected");
            sb.AppendLine();
            foreach (var c in contradictions)
                sb.AppendLine($"- {c}");
            try
            {
                await File.WriteAllTextAsync(contraPath, sb.ToString());
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException($"Failed to write contradictions page to '{contraPath}'", ex);
            }
        }
    }

}