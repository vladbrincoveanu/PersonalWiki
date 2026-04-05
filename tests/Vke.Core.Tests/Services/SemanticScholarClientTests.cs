using Vke.Core.Services;

namespace Vke.Core.Tests.Services;

public class SemanticScholarClientTests
{
    [Fact]
    public void GetPaperAsync_DeserializesCorrectly()
    {
        var json = @"{
            ""paperId"": ""10.48550/arXiv.2508.17906"",
            ""title"": ""Test Paper"",
            ""abstract"": ""This is a test abstract."",
            ""authors"": [{ ""name"": ""John Doe"" }],
            ""references"": []
        }";
        
        var paper = System.Text.Json.JsonSerializer.Deserialize<SemanticScholarPaper>(json);
        
        Assert.NotNull(paper);
        Assert.Equal("Test Paper", paper!.Title);
        Assert.Equal("This is a test abstract.", paper.Abstract);
        Assert.Single(paper.Authors);
        Assert.Equal("John Doe", paper.Authors[0].Name);
    }
}