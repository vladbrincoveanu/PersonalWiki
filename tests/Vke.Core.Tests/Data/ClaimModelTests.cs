using Vke.Core.Data.Models;

namespace Vke.Core.Tests.Data;

public class ClaimModelTests
{
    [Fact]
    public void Claim_DefaultVerificationStatus_IsUnverified()
    {
        var claim = new Claim();
        Assert.Equal(VerificationStatus.Unverified, claim.Status);
    }

    [Fact]
    public void Claim_CanStoreCorrectValue_WhenVerifiedFalse()
    {
        var claim = new Claim
        {
            Status = VerificationStatus.False,
            WrongReason = "Value should be $394.3B not $394B",
            CorrectValue = "394.3B",
            CorrectSource = "AAPL-10K-2024"
        };
        
        Assert.Equal("394.3B", claim.CorrectValue);
        Assert.Equal("AAPL-10K-2024", claim.CorrectSource);
    }
}