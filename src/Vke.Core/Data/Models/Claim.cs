namespace Vke.Core.Data.Models;

public class Claim
{
    public string Id { get; set; } = string.Empty;
    public string Statement { get; set; } = string.Empty;
    public string Normalized { get; set; } = string.Empty;
    public string SourceId { get; set; } = string.Empty;
    public string? Location { get; set; }
    public string? Domain { get; set; }
    public bool Verified { get; set; }
    public decimal VerificationScore { get; set; }
    public int Tier { get; set; } = 4;
    public int IndependentSourceCount { get; set; }
    public DateTime FirstSeen { get; set; } = DateTime.UtcNow;
    public DateTime? LastVerified { get; set; }
    public DateTime? StaleAfter { get; set; }
    public bool IsActive { get; set; } = true;
}