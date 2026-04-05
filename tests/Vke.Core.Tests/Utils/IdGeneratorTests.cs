using Vke.Core.Utils;

namespace Vke.Core.Tests.Utils;

public class IdGeneratorTests
{
    [Fact]
    public void GenerateSourceId_SameInputs_ProducesSameId()
    {
        var url = "https://www.sec.gov/Archives/edgar/data/320193/10k-2024.html";
        var date = new DateOnly(2024, 10, 28);
        
        var id1 = IdGenerator.GenerateSourceId(url, date);
        var id2 = IdGenerator.GenerateSourceId(url, date);
        
        Assert.Equal(id1, id2);
    }

    [Fact]
    public void GenerateSourceId_DifferentInputs_ProducesDifferentId()
    {
        var url1 = "https://www.sec.gov/Archives/edgar/data/320193/10k-2024.html";
        var url2 = "https://www.sec.gov/Archives/edgar/data/320193/10k-2023.html";
        var date = new DateOnly(2024, 10, 28);
        
        var id1 = IdGenerator.GenerateSourceId(url1, date);
        var id2 = IdGenerator.GenerateSourceId(url2, date);
        
        Assert.NotEqual(id1, id2);
    }

    [Fact]
    public void GenerateClaimId_CombinesNormalizedAndSourceId()
    {
        var normalized = "apple's revenue was $394.3b in fy2024";
        var sourceId = "abc123";
        
        var claimId = IdGenerator.GenerateClaimId(normalized, sourceId);
        
        Assert.StartsWith("claim-", claimId);
        Assert.Contains(sourceId, claimId);
    }
}