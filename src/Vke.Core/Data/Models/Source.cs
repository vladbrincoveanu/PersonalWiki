namespace Vke.Core.Data.Models;

public class Source
{
    public string Id { get; set; } = string.Empty;
    public string Url { get; set; } = string.Empty;
    public string? Title { get; set; }
    public string SourceType { get; set; } = string.Empty;
    public string? Author { get; set; }
    public string? Publication { get; set; }
    public DateOnly? PublishedAt { get; set; }
    public DateTime FetchedAt { get; set; } = DateTime.UtcNow;
    public string? Domain { get; set; }
    public List<string> CitesUrls { get; set; } = new();
    public List<string> CitesSourceIds { get; set; } = new();
    public bool IsActive { get; set; } = true;
    public int IndependentSourceCount { get; set; }
}