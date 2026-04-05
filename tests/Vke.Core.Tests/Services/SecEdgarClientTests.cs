using Vke.Core.Services;

namespace Vke.Core.Tests.Services;

public class SecEdgarClientTests
{
    [Fact]
    public void GetCompanyCik_ReturnsCorrectCik()
    {
        var mockHttp = new HttpClient();
        var client = new SecEdgarClient(mockHttp);
        
        var html = "Hello <b>World</b>&nbsp;&amp;";
        var result = SecEdgarClient.StripHtmlTags(html);
        
        Assert.DoesNotContain("<", result);
        Assert.DoesNotContain(">", result);
        Assert.Contains("Hello", result);
    }

    [Fact]
    public void FetchFilingContent_StripsHtmlTags()
    {
        var html = @"<html><body><p>Apple reported revenue of <b>$394.3 billion</b> in fiscal year 2024.</p></body></html>";
        var result = SecEdgarClient.StripHtmlTags(html);
        
        Assert.Contains("Apple reported revenue of", result);
        Assert.Contains("$394.3 billion", result);
        Assert.Contains("in fiscal year 2024.", result);
    }
}