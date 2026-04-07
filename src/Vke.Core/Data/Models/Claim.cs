namespace Vke.Core.Data.Models;

public class Claim
{
    public string Id { get; set; } = string.Empty;
    public string Statement { get; set; } = string.Empty;
    public string Normalized { get; set; } = string.Empty;
    public string SourceId { get; set; } = string.Empty;
    public string? Location { get; set; }
    public string? Domain { get; set; }
    public VerificationStatus Status { get; set; } = VerificationStatus.Unverified;
    public bool Verified {
        get => Status == VerificationStatus.Verified;
        set => Status = value ? VerificationStatus.Verified : VerificationStatus.Unverified;
    }
    public decimal VerificationScore { get; set; }
    
    public string? WrongReason { get; set; }
    public string? CorrectValue { get; set; }
    public string? CorrectSource { get; set; }
    public string? PrimarySourceUrl { get; set; }
    
    public int Tier { get; set; } = 4;
    public int IndependentSourceCount { get; set; }
    public DateTime FirstSeen { get; set; } = DateTime.UtcNow;
    public DateTime? LastVerified { get; set; }
    public DateTime? StaleAfter { get; set; }
    public bool IsActive { get; set; } = true;
    
    public DateTime? CorrectedAt { get; set; }
}