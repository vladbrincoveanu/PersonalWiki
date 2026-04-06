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
            new() { Statement = "Apple's revenue was $394.3B in FY2024", Status = VerificationStatus.Verified, Tier = 1, VerificationScore = 0.95m },
            new() { Statement = "Apple's net income was $97.0B in FY2024", Status = VerificationStatus.Verified, Tier = 1, VerificationScore = 0.92m },
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

    [Fact]
    public void GenerateEntityPage_CreatesHistorySnapshot()
    {
        var generator = new WikiGenerator();
        var claims = new List<Claim>
        {
            new() 
            { 
                Statement = "Apple revenue was $394.3B in FY2024", 
                Status = VerificationStatus.Verified, 
                CorrectValue = "394.3B",
                VerificationScore = 0.9m,
                Tier = 1
            }
        };
        
        var tempPath = Path.Combine(Path.GetTempPath(), $"wiki_test_{Guid.NewGuid()}");
        Directory.CreateDirectory(tempPath);
        
        generator.GenerateEntityPage("Apple Inc.", claims, tempPath, saveHistory: true);
        
        var historyDir = Path.Combine(tempPath, "entities", "apple-inc");
        Assert.True(Directory.Exists(historyDir));
        var files = Directory.GetFiles(historyDir, "*.md");
        Assert.Single(files);
        
        var historyContent = File.ReadAllText(files[0]);
        Assert.Contains("Apple Inc.", historyContent);
        Assert.Contains("$394.3B", historyContent);
        
        Directory.Delete(tempPath, true);
    }
}