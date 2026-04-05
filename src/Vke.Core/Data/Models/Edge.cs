namespace Vke.Core.Data.Models;

public class Edge
{
    public string SourceNode { get; set; } = string.Empty;
    public string TargetNode { get; set; } = string.Empty;
    public string Relation { get; set; } = string.Empty;
    public decimal Weight { get; set; } = 1.0m;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public string? CreatedBy { get; set; }
    public string? EvidenceSource { get; set; }
}