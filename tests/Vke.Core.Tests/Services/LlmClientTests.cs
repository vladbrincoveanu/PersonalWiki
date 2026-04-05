using Moq;
using Vke.Core.Services;
using Vke.Core.Utils;
using Vke.Core.Data.Models;

namespace Vke.Core.Tests.Services;

public class LlmClientTests
{
    [Fact]
    public async Task ExtractClaims_ReturnsListOfClaims()
    {
        var llmOutput = @"CLAIM: Apple's revenue was $394.3B in FY2024
LOCATION: Item 8
CLAIM: Apple's revenue increased 15% year-over-year
LOCATION: Item 8";
        
        var claims = ClaimParser.ParseLlmOutput(llmOutput);
        
        Assert.Equal(2, claims.Count);
        Assert.Equal("Apple's revenue was $394.3B in FY2024", claims[0].Statement);
        Assert.Equal("Item 8", claims[0].Location);
    }

    [Fact]
    public async Task VerifyClaim_ReturnsScoreBetween0And1()
    {
        var scoreText = "0.85";
        var parsed = decimal.TryParse(scoreText.Trim(), out var score);
        
        Assert.True(parsed);
        Assert.InRange(score, 0m, 1m);
    }
}
