namespace Vke.Core.Data.Models;

public class SourceType
{
    public string TypeKey { get; set; } = string.Empty;
    public string Label { get; set; } = string.Empty;
    public int BaseTier { get; set; }
    public decimal MaxConfidence { get; set; }
    public string? Description { get; set; }
    public string? Examples { get; set; }
}