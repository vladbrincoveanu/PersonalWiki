namespace Vke.Core.Data.Models;

public class RawFile
{
    public string Id { get; set; } = string.Empty;
    public string Filename { get; set; } = string.Empty;
    public string FullPath { get; set; } = string.Empty;
    public string Folder { get; set; } = string.Empty;
    public string? FileType { get; set; }
    public long? SizeBytes { get; set; }
    public DateTime? ModifiedAt { get; set; }
    public DateTime IndexedAt { get; set; } = DateTime.UtcNow;
    public string? LinkedEntity { get; set; }
    public string? LinkedSource { get; set; }
    public string Status { get; set; } = "pending";
}
