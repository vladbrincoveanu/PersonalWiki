using Vke.Core.Data;
using Vke.Core.Data.Models;

namespace Vke.Core.Tests.Data;

public class VkeDbContextTests : IDisposable
{
    private readonly string _dbPath = Path.Combine(Path.GetTempPath(), $"vke_test_{Guid.NewGuid()}.duckdb");
    private readonly VkeDbContext _db;

    public VkeDbContextTests()
    {
        _db = new VkeDbContext(_dbPath);
        _db.InitializeDatabase();
    }

    [Fact]
    public void InitializeDatabase_CreatesAllTables()
    {
        var tables = _db.Query<string>("SHOW TABLES").ToList();
        Assert.Contains("sources", tables);
        Assert.Contains("claims", tables);
        Assert.Contains("edges", tables);
        Assert.Contains("source_types", tables);
    }

    [Fact]
    public void InsertAndQuery_Source_RoundTrips()
    {
        var source = new Source
        {
            Id = "test-source-1",
            Url = "https://www.sec.gov/Archives/edgar/data/320193/0000320193-24-000012.html",
            Title = "Apple 10-K 2024",
            SourceType = "sec_10k",
            Author = "Apple Inc.",
            Domain = "financial",
            PublishedAt = new DateOnly(2024, 10, 28),
        };
        
        _db.InsertSource(source);
        var retrieved = _db.GetSourceById("test-source-1");
        
        Assert.NotNull(retrieved);
        Assert.Equal("Apple 10-K 2024", retrieved!.Title);
        Assert.Equal("sec_10k", retrieved.SourceType);
    }

    [Fact]
    public void InsertSourceType_Lookup_ReturnsCorrectTier()
    {
        var tier = _db.GetBaseTier("sec_10k");
        Assert.Equal(1, tier);
    }

    public void Dispose()
    {
        _db.Dispose();
        if (File.Exists(_dbPath))
            File.Delete(_dbPath);
    }
}