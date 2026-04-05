using System.Security.Cryptography;
using System.Text;

namespace Vke.Core.Utils;

public static class IdGenerator
{
    public static string GenerateSourceId(string url, DateOnly? publishedAt)
    {
        var input = $"{url}|{publishedAt?.ToString("yyyy-MM-dd") ?? "null"}";
        return "source-" + ComputeSha256(input);
    }

    public static string GenerateClaimId(string normalizedStatement, string sourceId)
    {
        var input = $"{normalizedStatement}|{sourceId}";
        return "claim-" + ComputeSha256(input);
    }

    private static string ComputeSha256(string input)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant()[..16];
    }
}