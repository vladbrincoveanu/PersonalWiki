using System.Text;
using Vke.Core.Data.Models;

namespace Vke.Core.Services;

public class WikiGenerator
{
    public async Task GenerateRawPage(Source source, List<Claim> claims, string rawPath)
    {
        Directory.CreateDirectory(rawPath);
        
        var filePath = Path.Combine(rawPath, $"{source.Id}.md");
        var sb = new StringBuilder();
        
        sb.AppendLine($"# {source.Title ?? source.Id}");
        sb.AppendLine();
        sb.AppendLine($"- **URL:** [{source.Url}]({source.Url})");
        sb.AppendLine($"- **Type:** {source.SourceType}");
        sb.AppendLine($"- **Author:** {source.Author ?? "Unknown"}");
        sb.AppendLine($"- **Published:** {source.PublishedAt?.ToString() ?? "Unknown"}");
        sb.AppendLine($"- **Domain:** {source.Domain}");
        sb.AppendLine($"- **Fetched:** {source.FetchedAt:yyyy-MM-dd HH:mm:ss}");
        sb.AppendLine();
        sb.AppendLine("## Content");
        sb.AppendLine();
        
        var content = source.Content ?? "";
        if (string.IsNullOrWhiteSpace(content))
        {
            sb.AppendLine("_No content available_");
        }
        else
        {
            var paragraphs = content.Split(new[] { "\n\n", "\r\n\r\n" }, StringSplitOptions.RemoveEmptyEntries);
            foreach (var para in paragraphs)
            {
                var trimmedPara = para.Trim();
                if (string.IsNullOrWhiteSpace(trimmedPara)) continue;
                
                var matchingClaims = claims.Where(c => 
                    trimmedPara.Contains(c.Statement, StringComparison.OrdinalIgnoreCase) ||
                    c.Statement.Contains(trimmedPara[..Math.Min(50, trimmedPara.Length)], StringComparison.OrdinalIgnoreCase)
                ).ToList();
                
                if (matchingClaims.Count != 0)
                {
                    foreach (var claim in matchingClaims)
                    {
                        var callout = GetCalloutForClaim(claim);
                        sb.AppendLine(callout);
                        sb.AppendLine();
                    }
                }
                else
                {
                    sb.AppendLine(trimmedPara);
                    sb.AppendLine();
                }
            }
        }
        
        sb.AppendLine("## All Claims");
        sb.AppendLine();
        
        foreach (var claim in claims)
        {
            var callout = GetCalloutForClaim(claim);
            sb.AppendLine(callout);
            sb.AppendLine();
        }
        
        await File.WriteAllTextAsync(filePath, sb.ToString());
    }

    public async Task GenerateVerifiedPage(Source source, List<Claim> claims, string verifiedPath, List<(string url, string description)>? sources = null)
    {
        Directory.CreateDirectory(verifiedPath);
        
        var fileName = SanitizeFileName(source.Title ?? source.Id) + ".md";
        var filePath = Path.Combine(verifiedPath, fileName);
        
        var verifiedClaims = claims
            .Where(c => c.Status == VerificationStatus.Verified && c.VerificationScore >= 0.6m)
            .ToList();
        
        if (verifiedClaims.Count == 0)
        {
            return;
        }
        
        var sb = new StringBuilder();
        sb.AppendLine($"# Verified Claims: {source.Title ?? source.Id}");
        sb.AppendLine();
        sb.AppendLine($"**Source:** [{source.Url}]({source.Url})");
        sb.AppendLine($"**Verified:** {DateTime.UtcNow:yyyy-MM-dd}");
        sb.AppendLine();
        sb.AppendLine("---");
        sb.AppendLine();
        
        foreach (var claim in verifiedClaims)
        {
            sb.AppendLine($"## Claim");
            sb.AppendLine();
            sb.AppendLine($"**Statement:** {claim.Statement}");
            sb.AppendLine();
            sb.AppendLine($"**Confidence:** {claim.VerificationScore:P0}");
            sb.AppendLine();
            
            if (!string.IsNullOrEmpty(claim.PrimarySourceUrl))
            {
                sb.AppendLine("**Sources:**");
                sb.AppendLine($"- [{claim.PrimarySourceUrl}]({claim.PrimarySourceUrl})");
                sb.AppendLine();
            }
            
            if (sources?.Any() == true)
            {
                sb.AppendLine("**References:**");
                foreach (var (url, desc) in sources)
                {
                    sb.AppendLine($"- [{desc}]({url})");
                }
                sb.AppendLine();
            }
            
            sb.AppendLine("---");
            sb.AppendLine();
        }
        
        await File.WriteAllTextAsync(filePath, sb.ToString());
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
            await File.WriteAllTextAsync(reviewPath, sb.ToString());
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
            await File.WriteAllTextAsync(stalePath, sb.ToString());
        }
        
        if (cycles.Any())
        {
            var cyclePath = Path.Combine(dir, "cycles.md");
            var sb = new StringBuilder();
            sb.AppendLine("# Circular Citation Alerts");
            sb.AppendLine();
            foreach (var cycle in cycles)
                sb.AppendLine($"- {cycle}");
            await File.WriteAllTextAsync(cyclePath, sb.ToString());
        }
        
        if (contradictions.Any())
        {
            var contraPath = Path.Combine(dir, "contradictions.md");
            var sb = new StringBuilder();
            sb.AppendLine("# Contradictions Detected");
            sb.AppendLine();
            foreach (var c in contradictions)
                sb.AppendLine($"- {c}");
            await File.WriteAllTextAsync(contraPath, sb.ToString());
        }
    }

    private static string GetCalloutForClaim(Claim claim)
    {
        var status = claim.Status switch
        {
            VerificationStatus.Verified when claim.VerificationScore >= 0.6m => "VERIFIED",
            VerificationStatus.Unverifiable => "UNVERIFIED",
            VerificationStatus.Unverified => "CANNOT_VERIFY",
            VerificationStatus.False => "FALSE",
            VerificationStatus.Disputed => "DISPUTED",
            VerificationStatus.Corrected => "CORRECTED",
            _ => "UNVERIFIED"
        };

        var icon = status switch
        {
            "VERIFIED" => "✅",
            "UNVERIFIED" => "⚠️",
            "CANNOT_VERIFY" => "❓",
            "FALSE" => "❌",
            "DISPUTED" => "🔸",
            "CORRECTED" => "🔄",
            _ => "⚪"
        };

        var sb = new StringBuilder();
        sb.AppendLine($"> [!{status}]");
        sb.AppendLine($"> {icon} {claim.Statement}");
        
        if (claim.VerificationScore > 0 && claim.VerificationScore < 1)
        {
            sb.AppendLine($">");
            sb.AppendLine($"> _Confidence: {claim.VerificationScore:P0}_");
        }
        
        if (!string.IsNullOrEmpty(claim.WrongReason))
        {
            sb.AppendLine($">");
            sb.AppendLine($"> _Reason: {claim.WrongReason}_");
        }
        
        if (!string.IsNullOrEmpty(claim.CorrectValue))
        {
            sb.AppendLine($">");
            sb.AppendLine($"> _Corrected to: {claim.CorrectValue}_");
        }
        
        if (!string.IsNullOrEmpty(claim.PrimarySourceUrl))
        {
            sb.AppendLine($">");
            sb.AppendLine($"> _Source: [{claim.PrimarySourceUrl}]({claim.PrimarySourceUrl})_");
        }
        
        if (status == "CANNOT_VERIFY")
        {
            sb.AppendLine($">");
            sb.AppendLine($"> _Needs human review_");
        }
        
        return sb.ToString();
    }

    public static string SanitizeFileName(string name)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var sanitized = new StringBuilder();
        foreach (var c in name)
        {
            sanitized.Append(invalid.Contains(c) ? '_' : c);
        }
        return sanitized.ToString();
    }
}
