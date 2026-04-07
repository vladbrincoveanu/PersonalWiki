using Vke.Core.Data.Models;
using Vke.Core.Services;

namespace Vke.Core.Tests.Services;

public class WikiGeneratorTests
{
    [Fact]
    public void GenerateVerifiedPage_CreatesValidMarkdown()
    {
        var generator = new WikiGenerator();
        var source = new Source
        {
            Id = "test-source-1",
            Url = "https://example.com/test",
            Title = "Test Source",
            SourceType = "generic",
            Domain = "test"
        };
        var claims = new List<Claim>
        {
            new() { Statement = "Apple's revenue was $394.3B in FY2024", Status = VerificationStatus.Verified, Tier = 1, VerificationScore = 0.95m },
            new() { Statement = "Apple's net income was $97.0B in FY2024", Status = VerificationStatus.Verified, Tier = 1, VerificationScore = 0.92m },
        };
        
        var wikiPath = Path.Combine(Path.GetTempPath(), $"wiki_test_{Guid.NewGuid()}");
        Directory.CreateDirectory(wikiPath);
        
        generator.GenerateVerifiedPage(source, claims, wikiPath).GetAwaiter().GetResult();
        
        var filePath = Directory.GetFiles(wikiPath, "*.md").FirstOrDefault();
        Assert.True(File.Exists(filePath));
        var content = File.ReadAllText(filePath!);
        Assert.Contains("Test Source", content);
        Assert.Contains("$394.3B", content);
        Assert.Contains("95%", content);
        
        Directory.Delete(wikiPath, true);
    }

    [Fact]
    public void GenerateRawPage_CreatesValidMarkdown()
    {
        var generator = new WikiGenerator();
        var source = new Source
        {
            Id = "test-source-1",
            Url = "https://example.com/test",
            Title = "Test Source",
            Content = "This is test content for the raw page. It should be preserved verbatim.",
            SourceType = "generic",
            Domain = "test"
        };
        var claims = new List<Claim>
        {
            new() { Statement = "Test claim", Status = VerificationStatus.Verified, VerificationScore = 0.9m },
        };
        
        var rawPath = Path.Combine(Path.GetTempPath(), $"wiki_test_{Guid.NewGuid()}");
        Directory.CreateDirectory(rawPath);
        
        generator.GenerateRawPage(source, claims, rawPath).GetAwaiter().GetResult();
        
        var filePath = Path.Combine(rawPath, "test-source-1.md");
        Assert.True(File.Exists(filePath));
        var content = File.ReadAllText(filePath);
        Assert.Contains("Test Source", content);
        Assert.Contains("verbatim", content);
        Assert.Contains("[!VERIFIED]", content);
        
        Directory.Delete(rawPath, true);
    }
}
