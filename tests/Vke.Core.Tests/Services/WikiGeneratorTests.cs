using Vke.Core.Data.Models;
using Vke.Core.Services;

namespace Vke.Core.Tests.Services;

public class WikiGeneratorTests
{
    [Fact]
    public void GenerateEntityPage_CreatesValidMarkdown()
    {
        var generator = new WikiGenerator();
        var claims = new List<Claim>
        {
            new() { Statement = "Apple's revenue was $394.3B in FY2024", Tier = 1, VerificationScore = 0.95m },
            new() { Statement = "Apple's net income was $97.0B in FY2024", Tier = 1, VerificationScore = 0.92m },
        };
        
        var wikiPath = Path.Combine(Path.GetTempPath(), $"wiki_test_{Guid.NewGuid()}");
        Directory.CreateDirectory(wikiPath);
        
        generator.GenerateEntityPage("Apple Inc.", claims, wikiPath);
        
        var filePath = Path.Combine(wikiPath, "entities", "apple-inc.md");
        Assert.True(File.Exists(filePath));
        var content = File.ReadAllText(filePath);
        Assert.Contains("Apple Inc.", content);
        Assert.Contains("$394.3B", content);
        
        Directory.Delete(wikiPath, true);
    }
}