using Vke.Core.Data;
using Vke.Core.Data.Models;

namespace Vke.Core.Tests.Data;

public class CircularCitationTests : IDisposable
{
    private readonly string _dbPath;
    private readonly VkeDbContext _db;

    public CircularCitationTests()
    {
        _dbPath = Path.Combine(Path.GetTempPath(), $"vke_cycle_test_{Guid.NewGuid()}.duckdb");
        _db = new VkeDbContext(_dbPath);
        _db.InitializeDatabase();
    }

    [Fact]
    public void DetectCycles_CircularChain_ReturnsCycle()
    {
        _db.InsertSource(new Source { Id = "A", Url = "http://a.com", SourceType = "sec_10k", Domain = "financial" });
        _db.InsertSource(new Source { Id = "B", Url = "http://b.com", SourceType = "news_wire", Domain = "news" });
        _db.InsertSource(new Source { Id = "C", Url = "http://c.com", SourceType = "news_article", Domain = "news" });
        
        _db.InsertEdge(new Edge { SourceNode = "A", TargetNode = "B", Relation = "source_cites_source", CreatedBy = "test" });
        _db.InsertEdge(new Edge { SourceNode = "B", TargetNode = "C", Relation = "source_cites_source", CreatedBy = "test" });
        _db.InsertEdge(new Edge { SourceNode = "C", TargetNode = "A", Relation = "source_cites_source", CreatedBy = "test" });
        
        var cycles = _db.DetectCycles();
        
        Assert.NotEmpty(cycles);
        Assert.Contains(cycles, c => c.Contains("A") && c.Contains("B") && c.Contains("C"));
    }

    [Fact]
    public void GetRootSources_ThreeSourcesCitingUpstream_ReturnsOneRoot()
    {
        _db.InsertSource(new Source { Id = "sec", Url = "http://sec.gov/10k", SourceType = "sec_10k", Domain = "financial" });
        _db.InsertSource(new Source { Id = "reuters", Url = "http://reuters.com", SourceType = "news_wire", Domain = "news" });
        _db.InsertSource(new Source { Id = "wsj", Url = "http://wsj.com", SourceType = "news_article", Domain = "news" });
        _db.InsertSource(new Source { Id = "blog", Url = "http://blog.com", SourceType = "blog_post", Domain = "news" });
        
        _db.InsertEdge(new Edge { SourceNode = "reuters", TargetNode = "sec", Relation = "source_cites_source", CreatedBy = "test" });
        _db.InsertEdge(new Edge { SourceNode = "wsj", TargetNode = "reuters", Relation = "source_cites_source", CreatedBy = "test" });
        _db.InsertEdge(new Edge { SourceNode = "blog", TargetNode = "wsj", Relation = "source_cites_source", CreatedBy = "test" });
        
        _db.InsertEdge(new Edge { SourceNode = "sec", TargetNode = "test-claim", Relation = "source_asserts_claim", CreatedBy = "test" });
        _db.InsertEdge(new Edge { SourceNode = "reuters", TargetNode = "test-claim", Relation = "source_asserts_claim", CreatedBy = "test" });
        _db.InsertEdge(new Edge { SourceNode = "wsj", TargetNode = "test-claim", Relation = "source_asserts_claim", CreatedBy = "test" });
        _db.InsertEdge(new Edge { SourceNode = "blog", TargetNode = "test-claim", Relation = "source_asserts_claim", CreatedBy = "test" });
        
        var roots = _db.GetRootSourcesForClaim("test-claim");
        
        Assert.Single(roots);
        Assert.Equal("sec", roots[0]);
    }

    public void Dispose()
    {
        _db.Dispose();
        if (File.Exists(_dbPath))
            File.Delete(_dbPath);
    }
}