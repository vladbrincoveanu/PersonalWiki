using Vke.Core.Data.Models;

namespace Vke.Core.Tests.Data;

public class SourceModelTests
{
    [Fact]
    public void Source_DefaultValues_AreCorrect()
    {
        var source = new Source();
        Assert.Equal(string.Empty, source.Id);
        Assert.Equal(string.Empty, source.Url);
        Assert.Equal(string.Empty, source.SourceType);
        Assert.True(source.IsActive);
        Assert.Equal(0, source.IndependentSourceCount);
    }
}