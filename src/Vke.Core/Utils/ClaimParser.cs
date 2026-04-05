using Vke.Core.Data.Models;

namespace Vke.Core.Utils;

public static class ClaimParser
{
    public static List<Claim> ParseLlmOutput(string llmOutput)
    {
        var claims = new List<Claim>();
        var lines = llmOutput.Split('\n', StringSplitOptions.RemoveEmptyEntries);
        Claim? currentClaim = null;

        foreach (var line in lines)
        {
            var trimmed = line.Trim();
            if (trimmed.StartsWith("CLAIM:", StringComparison.OrdinalIgnoreCase))
            {
                currentClaim = new Claim
                {
                    Statement = trimmed["CLAIM:".Length..].Trim(),
                    Normalized = Normalize(trimmed["CLAIM:".Length..].Trim()),
                };
            }
            else if (trimmed.StartsWith("LOCATION:", StringComparison.OrdinalIgnoreCase) && currentClaim != null)
            {
                currentClaim.Location = trimmed["LOCATION:".Length..].Trim();
                claims.Add(currentClaim);
                currentClaim = null;
            }
        }

        return claims;
    }

    private static string Normalize(string statement)
    {
        return statement.ToLowerInvariant()
            .Replace("$", "")
            .Replace(",", "")
            .Replace(".", "")
            .Replace("  ", " ")
            .Trim();
    }
}
