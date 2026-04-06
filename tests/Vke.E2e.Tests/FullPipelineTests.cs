using Vke.Core.Data;
using Vke.Core.Data.Models;
using Vke.Core.Agents;
using Vke.Core.Services;
using Moq;

namespace Vke.E2e.Tests;

public class FullPipelineTests : IDisposable
{
    private readonly string _testVaultPath;
    private readonly string _dbPath;
    
    public FullPipelineTests()
    {
        _testVaultPath = Path.Combine(Path.GetTempPath(), $"vke_e2e_{Guid.NewGuid()}");
        _dbPath = Path.Combine(_testVaultPath, "vke.duckdb");
        Directory.CreateDirectory(_testVaultPath);
        Directory.CreateDirectory(Path.Combine(_testVaultPath, "raw"));
        Directory.CreateDirectory(Path.Combine(_testVaultPath, "wiki"));
    }

    [Fact]
    public async Task FullPipeline_IngestNewsArticle_VerifiesAndStoresCorrectly()
    {
        using var db = new VkeDbContext(_dbPath);
        db.InitializeDatabase();
        
        var mockLlm = new Mock<ILlmClient>();
        var mockYahooFinance = new Mock<IYahooFinanceClient>();
        
        mockLlm.Setup(x => x.VerifyClaimAsync(It.IsAny<string>(), It.IsAny<string>()))
            .ReturnsAsync(0.3m);
        
        mockYahooFinance.Setup(x => x.GetRevenueAsync("AAPL", It.IsAny<string>()))
            .ReturnsAsync(("394.3B", "https://finance.yahoo.com/aapl"));
        
        var secSource = new Source
        {
            Id = "sec-1",
            Url = "https://www.sec.gov/Archives/edgar/data/320193/10k-2024.html",
            Title = "Apple 10-K FY2024",
            SourceType = "sec_10k",
            Domain = "financial",
            Content = "Apple reported revenue of $394.3 billion in FY2024."
        };
        db.InsertSource(secSource);
        
        var gtClaim = new Claim
        {
            Id = "gt-claim-1",
            Statement = "Apple revenue was $394.3B in FY2024",
            Normalized = "apple revenue was 394.3b in fy2024",
            SourceId = "sec-1",
            Status = VerificationStatus.Verified,
            VerificationScore = 0.95m,
            Tier = 1,
            Verified = true
        };
        db.InsertClaim(gtClaim);
        db.InsertEdge(new Edge
        {
            SourceNode = "sec-1",
            TargetNode = "gt-claim-1",
            Relation = "source_asserts_claim",
            CreatedBy = "test"
        });
        
        var newsSource = new Source
        {
            Id = "news-1",
            Url = "https://example.com/apple-revenue-article",
            Title = "Apple Revenue Article",
            SourceType = "news_article",
            Domain = "financial",
            Content = "Apple revenue was $394 billion in FY2024"
        };
        db.InsertSource(newsSource);
        
        var newsClaim = new Claim
        {
            Statement = "Apple revenue was $394 billion in FY2024",
            Normalized = "apple revenue was 394.3b in fy2024",
            SourceId = "news-1",
            Status = VerificationStatus.Unverified
        };
        
        var wikiPath = Path.Combine(_testVaultPath, "wiki");
        var verifyAgent = new VerifyAgent(db, mockLlm.Object, null, wikiPath);
        var result = await verifyAgent.VerifyAndStoreAsync("news-1", new List<Claim> { newsClaim });
        
        Assert.Equal(1, result.False);
        Assert.Equal(VerificationStatus.False, newsClaim.Status);
        Assert.NotNull(newsClaim.WrongReason);
        
        var rawPath = Path.Combine(_testVaultPath, "raw", "news-1.md");
        Assert.True(File.Exists(rawPath), "Raw file should be created");
        var rawContent = File.ReadAllText(rawPath);
        Assert.Contains("[VERIFIED=FALSE", rawContent);
        
        var correctionAgent = new CorrectionAgent(db, mockYahooFinance.Object, null);
        var corrections = await correctionAgent.ProcessStaleAndFalseClaimsAsync();
        
        Assert.Single(corrections);
        Assert.Equal("394.3B", corrections[0].CorrectValue);
        
        var updatedClaim = db.GetClaimsByStatus(VerificationStatus.Corrected).FirstOrDefault();
        Assert.NotNull(updatedClaim);
        Assert.Equal("394.3B", updatedClaim.CorrectValue);
    }

    [Fact]
    public void Database_Schema_HasAllRequiredColumns()
    {
        using var db = new VkeDbContext(_dbPath);
        db.InitializeDatabase();
        
        var columns = db.Query<string>("SELECT name FROM pragma_table_info('claims')").ToList();
        
        Assert.Contains("status", columns);
        Assert.Contains("wrong_reason", columns);
        Assert.Contains("correct_value", columns);
        Assert.Contains("correct_source", columns);
        Assert.Contains("corrected_at", columns);
    }

    public void Dispose()
    {
        if (Directory.Exists(_testVaultPath))
            Directory.Delete(_testVaultPath, recursive: true);
    }
}