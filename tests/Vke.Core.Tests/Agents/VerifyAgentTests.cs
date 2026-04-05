using Moq;
using Vke.Core.Agents;
using Vke.Core.Data;
using Vke.Core.Data.Models;
using Vke.Core.Services;
using Vke.Core.Utils;

namespace Vke.Core.Tests.Agents;

public class VerifyAgentTests : IDisposable
{
    private readonly string _dbPath;
    private readonly VkeDbContext _db;

    public VerifyAgentTests()
    {
        _dbPath = Path.Combine(Path.GetTempPath(), $"vke_verify_test_{Guid.NewGuid()}.duckdb");
        _db = new VkeDbContext(_dbPath);
        _db.InitializeDatabase();
    }

    [Fact]
    public async Task VerifyAndStore_ClaimPassesThreshold_StoresVerifiedClaim()
    {
        var mockLlm = new Mock<ILlmClient>();
        mockLlm.Setup(x => x.VerifyClaimAsync(It.IsAny<string>(), It.IsAny<string>()))
            .ReturnsAsync(0.85m);
        
        _db.InsertSource(new Source
        {
            Id = "source-1",
            Url = "http://sec.gov/10k",
            SourceType = "sec_10k",
            Domain = "financial",
        });
        
        var agent = new VerifyAgent(_db, mockLlm.Object);
        var claims = new List<Claim>
        {
            new() { Statement = "Apple's revenue was $394.3B in FY2024", Normalized = "apples revenue was 3943b in fy2024", SourceId = "source-1" }
        };
        
        var result = await agent.VerifyAndStoreAsync("source-1", claims);
        
        Assert.Equal(1, result.Verified);
        Assert.Equal(0, result.Quarantined);
        
        var claimId = IdGenerator.GenerateClaimId("apples revenue was 3943b in fy2024", "source-1");
        var stored = _db.GetClaimById(claimId);
        Assert.NotNull(stored);
        Assert.True(stored.Verified);
    }

    [Fact]
    public async Task VerifyAndStore_ClaimFailsThreshold_QuarantinesClaim()
    {
        var mockLlm = new Mock<ILlmClient>();
        mockLlm.Setup(x => x.VerifyClaimAsync(It.IsAny<string>(), It.IsAny<string>()))
            .ReturnsAsync(0.3m);
        
        _db.InsertSource(new Source
        {
            Id = "source-1",
            Url = "http://sec.gov/10k",
            SourceType = "sec_10k",
            Domain = "financial",
        });
        
        var agent = new VerifyAgent(_db, mockLlm.Object);
        var claims = new List<Claim>
        {
            new() { Statement = "Apple's revenue was $1T in FY2024", Normalized = "apples revenue was 1t in fy2024", SourceId = "source-1" }
        };
        
        var result = await agent.VerifyAndStoreAsync("source-1", claims);
        
        Assert.Equal(0, result.Verified);
        Assert.Equal(1, result.Quarantined);
    }

    public void Dispose()
    {
        _db.Dispose();
        if (File.Exists(_dbPath))
            File.Delete(_dbPath);
    }
}