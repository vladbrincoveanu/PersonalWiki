using Vke.Core.Utils;

namespace Vke.Core.Tests.Utils;

public class InlineAnnotationTests
{
    [Fact]
    public void Annotate_InsertsVerificationMarker_AtCorrectLocation()
    {
        var content = "Apple reported revenue of $394 billion in FY2024.";
        var annotation = VerificationAnnotation.False(
            reason: "Should be $394.3B not $394B",
            correctValue: "394.3B",
            source: "AAPL-10K-2024"
        );
        
        var result = InlineAnnotation.Annotate(content, "394 billion", annotation);
        
        Assert.Contains("[VERIFIED=FALSE", result);
        Assert.Contains("reason=\"Should be $394.3B not $394B\"", result);
        Assert.Contains("correct_value=\"394.3B\"", result);
    }

    [Fact]
    public void ExtractAnnotations_ParsesAllMarkers_FromContent()
    {
        var content = @"Apple revenue was $394 billion [VERIFIED=FALSE reason=""Should be 394.3B"" source=""AAPL-10K""]
        Net income was $97B.";
        
        var annotations = InlineAnnotation.ExtractAnnotations(content);
        
        Assert.Single(annotations);
        Assert.Equal("Should be 394.3B", annotations[0].Reason);
    }
}