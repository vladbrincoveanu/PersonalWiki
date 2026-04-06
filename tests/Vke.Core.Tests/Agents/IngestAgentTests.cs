using Moq;
using Vke.Core.Agents;
using Vke.Core.Data;
using Vke.Core.Data.Models;
using Vke.Core.Services;

namespace Vke.Core.Tests.Agents;

public class IngestAgentTests
{
    [Fact]
    public async Task IngestSecFiling_StoresSourceAndClaims()
    {
        var dbPath = Path.Combine(Path.GetTempPath(), $"vke_ingest_test_{Guid.NewGuid()}.duckdb");
        var db = new VkeDbContext(dbPath);
        db.InitializeDatabase();
        
        var mockLlm = new Mock<ILlmClient>();
        mockLlm.Setup(x => x.ExtractClaimsAsync(It.IsAny<string>(), It.IsAny<string>()))
            .ReturnsAsync(new List<Claim>
            {
                new() { Statement = "Apple's revenue was $394.3B in FY2024", Location = "Item 8" },
            });
        
        var mockSec = new Mock<SecEdgarClient>(MockBehavior.Loose, new HttpClient());
        mockSec.Setup(x => x.FetchFilingContentAsync(It.IsAny<string>()))
            .ReturnsAsync("Apple reported revenue of $394.3 billion in fiscal year 2024...");
        
        var agent = new IngestAgent(db, mockLlm.Object, mockSec.Object, null, null);
        
        var (sourceId, claims) = await agent.IngestAsync("https://www.sec.gov/...10k.html", "sec_10k", "financial");
        
        Assert.NotEmpty(sourceId);
        Assert.Single(claims);
        Assert.Equal("Apple's revenue was $394.3B in FY2024", claims[0].Statement);
        
        db.Dispose();
        File.Delete(dbPath);
    }
}