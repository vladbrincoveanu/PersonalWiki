using Moq;
using Vke.Core.Agents;
using Vke.Core.Data;
using Vke.Core.Data.Models;
using Vke.Core.Services;

namespace Vke.Core.Tests.Agents;

public class FakeYahooFinanceClient : IYahooFinanceClient
{
    public Func<string, string, (string value, string sourceUrl)?>? GetRevenueFunc { get; set; }
    public Func<string, (string value, string sourceUrl)?>? GetStockPriceFunc { get; set; }

    public Task<(string value, string sourceUrl)?> GetRevenueAsync(string ticker, string period)
    {
        var result = GetRevenueFunc?.Invoke(ticker, period);
        return Task.FromResult(result);
    }

    public Task<(string value, string sourceUrl)?> GetStockPriceAsync(string ticker)
    {
        var result = GetStockPriceFunc?.Invoke(ticker);
        return Task.FromResult(result);
    }
}

public class CorrectionAgentTests : IDisposable
{
    private readonly string _dbPath;
    private readonly VkeDbContext _db;

    public CorrectionAgentTests()
    {
        _dbPath = Path.Combine(Path.GetTempPath(), $"vke_correction_test_{Guid.NewGuid()}.duckdb");
        _db = new VkeDbContext(_dbPath);
        _db.InitializeDatabase();
    }

    [Fact]
    public async Task FindCorrectValue_ForFinancialClaim_QueriesAuthoritativeSource()
    {
        _db.InsertSource(new Source
        {
            Id = "test-source-1",
            Url = "https://example.com/article",
            SourceType = "news_article",
            Domain = "financial"
        });

        var falseClaim = new Claim
        {
            Id = "test-claim-1",
            Statement = "Apple revenue was $394B in FY2024",
            Normalized = "apple revenue was 394b in fy2024",
            Status = VerificationStatus.False,
            WrongReason = "Should be $394.3B",
            SourceId = "test-source-1"
        };
        _db.InsertClaim(falseClaim);
        
        var fakeYahooFinance = new FakeYahooFinanceClient();
        fakeYahooFinance.GetRevenueFunc = (ticker, period) =>
        {
            if (ticker == "AAPL" && period == "FY2024")
                return ("394.3B", "https://finance.yahoo.com/aapl");
            return null;
        };
        
        var agent = new CorrectionAgent(_db, fakeYahooFinance, null);
        var result = await agent.FindCorrectValueAsync(falseClaim);
        
        Assert.NotNull(result);
        Assert.True(result.HasValue);
        Assert.Equal("394.3B", result.Value.value);
        Assert.NotNull(result.Value.sourceUrl);
    }

    [Fact]
    public async Task ProcessStaleAndFalseClaims_UpdatesClaimsWithCorrectValues()
    {
        _db.InsertSource(new Source
        {
            Id = "test-source-2",
            Url = "https://example.com/article2",
            SourceType = "news_article",
            Domain = "financial"
        });

        var falseClaim = new Claim
        {
            Id = "test-claim-2",
            Statement = "Microsoft revenue was $227B in FY2024",
            Normalized = "microsoft revenue was 227b in fy2024",
            Status = VerificationStatus.False,
            WrongReason = "Should be $245B",
            SourceId = "test-source-2"
        };
        _db.InsertClaim(falseClaim);
        
        var fakeYahooFinance = new FakeYahooFinanceClient();
        fakeYahooFinance.GetRevenueFunc = (ticker, period) =>
        {
            if (ticker == "MSFT" && period == "FY2024")
                return ("245B", "https://finance.yahoo.com/msft");
            return null;
        };
        
        var agent = new CorrectionAgent(_db, fakeYahooFinance, null);
        var results = await agent.ProcessStaleAndFalseClaimsAsync();
        
        Assert.Single(results);
        Assert.Equal("test-claim-2", results[0].ClaimId);
        Assert.Equal("245B", results[0].CorrectValue);
        
        var updatedClaim = _db.GetClaimById("test-claim-2");
        Assert.NotNull(updatedClaim);
        Assert.Equal(VerificationStatus.Corrected, updatedClaim.Status);
        Assert.NotNull(updatedClaim.CorrectedAt);
    }

    [Fact]
    public async Task FindCorrectValue_UnknownTicker_ReturnsNull()
    {
        _db.InsertSource(new Source
        {
            Id = "test-source-3",
            Url = "https://example.com/article3",
            SourceType = "news_article",
            Domain = "financial"
        });

        var falseClaim = new Claim
        {
            Id = "test-claim-3",
            Statement = "UnknownCorp revenue was $100B in FY2024",
            Normalized = "unknowncorp revenue was 100b in fy2024",
            Status = VerificationStatus.False,
            SourceId = "test-source-3"
        };
        _db.InsertClaim(falseClaim);
        
        var fakeYahooFinance = new FakeYahooFinanceClient();
        var agent = new CorrectionAgent(_db, fakeYahooFinance, null);
        var result = await agent.FindCorrectValueAsync(falseClaim);
        
        Assert.Null(result);
    }

    public void Dispose()
    {
        _db.Dispose();
        if (File.Exists(_dbPath))
            File.Delete(_dbPath);
    }
}