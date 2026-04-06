using System.Text;
using System.Text.RegularExpressions;
using Vke.Core.Data.Models;

namespace Vke.Core.Utils;

public record VerificationAnnotation(
    VerificationStatus Status,
    string Reason,
    string? CorrectValue = null,
    string? Source = null,
    DateTime AnnotatedAt = default
)
{
    public static VerificationAnnotation False(string reason, string? correctValue = null, string? source = null)
        => new(VerificationStatus.False, reason, correctValue, source, DateTime.UtcNow);

    public static VerificationAnnotation Disputed(string reason, string? source = null)
        => new(VerificationStatus.Disputed, reason, null, source, DateTime.UtcNow);

    public static VerificationAnnotation Unverifiable(string reason)
        => new(VerificationStatus.Unverifiable, reason, null, null, DateTime.UtcNow);

    public override string ToString()
    {
        var sb = new StringBuilder();
        sb.Append($"[VERIFIED={Status.ToString().ToUpperInvariant()}");
        if (!string.IsNullOrEmpty(Reason))
            sb.Append($" reason=\"{Reason.Replace("\"", "&quot;")}\"");
        if (!string.IsNullOrEmpty(CorrectValue))
            sb.Append($" correct_value=\"{CorrectValue}\"");
        if (!string.IsNullOrEmpty(Source))
            sb.Append($" source=\"{Source}\"");
        sb.Append(']');
        return sb.ToString();
    }
}

public static class InlineAnnotation
{
    private static readonly Regex AnnotationPattern = new(
        @"\[VERIFIED=(?<status>\w+)(?<attrs>(?:\s+\w+=""[^""]*"")*)\]",
        RegexOptions.Compiled);

    public static string Annotate(string content, string matchedText, VerificationAnnotation annotation)
    {
        var marker = annotation.ToString();
        var pattern = Regex.Escape(matchedText);
        return Regex.Replace(content, pattern, $"{matchedText}{marker}", RegexOptions.IgnoreCase);
    }

    public static List<VerificationAnnotation> ExtractAnnotations(string content)
    {
        var annotations = new List<VerificationAnnotation>();
        
        foreach (Match match in AnnotationPattern.Matches(content))
        {
            var status = Enum.TryParse<VerificationStatus>(match.Groups["status"].Value, out var s) 
                ? s : VerificationStatus.Unverified;
            
            var reason = match.Groups["attrs"].Value.Contains("reason=") 
                ? ExtractAttr(match.Groups["attrs"].Value, "reason") : null;
            var correctValue = match.Groups["attrs"].Value.Contains("correct_value=") 
                ? ExtractAttr(match.Groups["attrs"].Value, "correct_value") : null;
            var source = match.Groups["attrs"].Value.Contains("source=") 
                ? ExtractAttr(match.Groups["attrs"].Value, "source") : null;
            
            annotations.Add(new VerificationAnnotation(status, reason ?? "", correctValue, source));
        }
        
        return annotations;
    }

    private static readonly Regex AttrPattern = new(
        @"(?<name>\w+)=""(?<value>[^""]*)""",
        RegexOptions.Compiled);
    
    private static string? ExtractAttr(string attrs, string name)
    {
        var match = AttrPattern.Match(attrs);
        while (match.Success)
        {
            if (match.Groups["name"].Value == name)
                return match.Groups["value"].Value;
            match = match.NextMatch();
        }
        return null;
    }
}