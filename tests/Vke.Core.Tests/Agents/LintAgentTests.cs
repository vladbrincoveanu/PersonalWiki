using Vke.Core.Agents;
using Vke.Core.Data;
using Vke.Core.Data.Models;

namespace Vke.Core.Tests.Agents;

public class LintAgentTests : IDisposable
{
    private readonly string _dbPath;
    private readonly VkeDbContext _db;

    public LintAgentTests()
    {
        _dbPath = Path.Combine(Path.GetTempPath(), $"vke_lint_test_{Guid.NewGuid()}.duckdb");
        _db = new VkeDbContext(_dbPath);
        _db.InitializeDatabase();
    }

    [Fact]
    public void ScanStaleClaims_ReturnsClaimsPastStaleDate()
    {
        _db.InsertSource(new Source { Id = "s1", Url = "http://a.com", SourceType = "sec_10k", Domain = "financial" });
        
        var staleDate = DateTime.UtcNow.AddDays(-10);
        _db.InsertClaim(new Claim
        {
            Id = "c1",
            Statement = "Old claim",
            Normalized = "old claim",
            SourceId = "s1",
            StaleAfter = staleDate,
            Status = VerificationStatus.Verified,
        });
        
        var agent = new LintAgent(_db);
        var stale = agent.ScanStaleClaims();
        
        Assert.Single(stale);
        Assert.Equal("c1", stale[0].Id);
    }

    [Fact]
    public void FindOrphans_ReturnsSourcesWithNoClaims()
    {
        _db.InsertSource(new Source { Id = "orphan", Url = "http://orphan.com", SourceType = "sec_10k", Domain = "financial" });
        
        var agent = new LintAgent(_db);
        var orphans = agent.FindOrphanSources();
        
        Assert.Single(orphans);
        Assert.Equal("orphan", orphans[0].Id);
    }

    public void Dispose()
    {
        _db.Dispose();
        if (File.Exists(_dbPath))
            File.Delete(_dbPath);
    }
}