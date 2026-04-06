namespace Vke.Core.Utils;

public static class StringUtils
{
    public static string ToFileName(string text)
    {
        return text.ToLowerInvariant()
            .Replace(" ", "-")
            .Replace(".", "")
            .Replace(",", "")
            .Replace("'", "")
            .Replace(":", "");
    }
}
