using Vke.Core.Data;
using Vke.Core.Data.Models;
using Vke.Core.Services;

namespace Vke.Core.Agents;

public class CorrectionAgent
{
    private static readonly System.Text.RegularExpressions.Regex YearPatternRegex = new(@"(19|20)\d{2}", System.Text.RegularExpressions.RegexOptions.Compiled);
    private static readonly System.Text.RegularExpressions.Regex PeriodPatternRegex = new(@"(FY|Q[1-4])\s*202[0-9]", System.Text.RegularExpressions.RegexOptions.Compiled);

    private readonly VkeDbContext _db;
    private readonly IYahooFinanceClient _yahooFinance;
    private readonly SecEdgarClient? _secEdgar;

    public CorrectionAgent(VkeDbContext db, IYahooFinanceClient yahooFinance, SecEdgarClient? secEdgar = null)
    {
        _db = db;
        _yahooFinance = yahooFinance;
        _secEdgar = secEdgar;
    }

    public async Task<List<CorrectionResult>> ProcessStaleAndFalseClaimsAsync()
    {
        var results = new List<CorrectionResult>();
        
        var falseClaims = _db.GetClaimsByStatus(VerificationStatus.False)
            .Where(c => string.IsNullOrEmpty(c.CorrectValue))
            .ToList();
        
        foreach (var claim in falseClaims)
        {
            var result = await FindCorrectValueAsync(claim);
            if (result.HasValue)
            {
                claim.CorrectValue = result.Value.value;
                claim.CorrectSource = result.Value.sourceUrl;
                claim.CorrectedAt = DateTime.UtcNow;
                claim.Status = VerificationStatus.Corrected;
                
                _db.UpdateClaim(claim);
                results.Add(new CorrectionResult
                {
                    ClaimId = claim.Id,
                    OriginalValue = claim.Statement,
                    CorrectValue = result.Value.value,
                    Source = result.Value.sourceUrl
                });
            }
        }
        
        var staleClaims = _db.GetStaleClaims();
        foreach (var claim in staleClaims)
        {
            var result = await FindCorrectValueAsync(claim);
            if (result.HasValue)
            {
                claim.CorrectValue = result.Value.value;
                claim.CorrectSource = result.Value.sourceUrl;
                claim.CorrectedAt = DateTime.UtcNow;
                claim.StaleAfter = DateTime.UtcNow.AddDays(90);
                
                _db.UpdateClaim(claim);
                results.Add(new CorrectionResult
                {
                    ClaimId = claim.Id,
                    OriginalValue = claim.Statement,
                    CorrectValue = result.Value.value,
                    Source = result.Value.sourceUrl,
                    IsRefresh = true
                });
            }
        }
        
        return results;
    }

    public async Task<(string value, string sourceUrl)?> FindCorrectValueAsync(Claim claim)
    {
        var (entity, metric) = ParseEntityAndMetric(claim.Statement);
        
        if (entity == null || metric == null)
            return null;

        var ticker = ResolveTicker(entity);
        if (ticker != null)
        {
            if (metric.Contains("revenue", StringComparison.OrdinalIgnoreCase))
            {
                var result = await _yahooFinance.GetRevenueAsync(ticker, ExtractPeriod(claim.Statement));
                if (result.HasValue) return result;
            }
            else if (metric.Contains("price", StringComparison.OrdinalIgnoreCase) || metric.Contains("stock", StringComparison.OrdinalIgnoreCase))
            {
                var result = await _yahooFinance.GetStockPriceAsync(ticker);
                if (result.HasValue) return result;
            }
        }

        return null;
    }

    private static (string? entity, string? metric) ParseEntityAndMetric(string statement)
    {
        var words = statement.Split(' ');
        string? entity = null;
        string? metric = null;
        
        var financialTerms = new[] { "revenue", "income", "profit", "loss", "price", "stock", "eps", "shares", "dividend", "ebitda", "margin" };
        var yearPattern = YearPatternRegex.IsMatch(statement);
        
        for (int i = 0; i < words.Length; i++)
        {
            var word = words[i].Trim(',', '.', ':', '$');
            
            if (entity == null && word.Length > 1 && char.IsUpper(word[0]) && !financialTerms.Any(t => word.Equals(t, StringComparison.OrdinalIgnoreCase)))
            {
                var containsYear = YearPatternRegex.IsMatch(word);
                if (!(yearPattern && containsYear))
                {
                    entity = word;
                }
            }
            
            if (metric == null)
            {
                foreach (var term in financialTerms)
                {
                    if (statement.Contains(term, StringComparison.OrdinalIgnoreCase))
                    {
                        metric = term;
                        break;
                    }
                }
            }
        }
        
        return (entity, metric);
    }

    private static string ExtractPeriod(string statement)
    {
        var match = PeriodPatternRegex.Match(statement);
        return match.Success ? match.Value : "FY2024";
    }

    private static string? ResolveTicker(string entity)
    {
        var knownTickers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { "Apple", "AAPL" },
            { "Microsoft", "MSFT" },
            { "Nvidia", "NVDA" },
            { "Google", "GOOGL" },
            { "Amazon", "AMZN" },
            { "Meta", "META" },
            { "Tesla", "TSLA" },
        };
        
        return knownTickers.TryGetValue(entity, out var ticker) ? ticker : null;
    }
}

public record CorrectionResult
{
    public string ClaimId { get; init; } = "";
    public string OriginalValue { get; init; } = "";
    public string CorrectValue { get; init; } = "";
    public string Source { get; init; } = "";
    public bool IsRefresh { get; init; }
}