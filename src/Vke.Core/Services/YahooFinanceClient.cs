using System.Net.Http.Json;

namespace Vke.Core.Services;

public interface IYahooFinanceClient
{
    Task<(string value, string sourceUrl)?> GetRevenueAsync(string ticker, string period);
    Task<(string value, string sourceUrl)?> GetStockPriceAsync(string ticker);
}

public class YahooFinanceClient : IYahooFinanceClient
{
    private readonly HttpClient _http;

    public YahooFinanceClient(HttpClient http)
    {
        _http = http;
    }

    public virtual async Task<(string value, string sourceUrl)?> GetRevenueAsync(string ticker, string period)
    {
        try
        {
            var response = await _http.GetFromJsonAsync<YahooFinanceResponse>(
                $"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=financialData"
            );
            
            var revenue = response?.QuoteSummary?.FinancialData?.TotalRevenue?.Raw;
            if (revenue.HasValue)
            {
                var formatted = FormatRevenue(revenue.Value);
                return (formatted, $"https://finance.yahoo.com/quote/{ticker}");
            }
        }
        catch (Exception)
        {
        }
        
        return null;
    }

    public virtual async Task<(string value, string sourceUrl)?> GetStockPriceAsync(string ticker)
    {
        try
        {
            var response = await _http.GetFromJsonAsync<YahooFinanceResponse>(
                $"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=price"
            );
            
            var price = response?.QuoteSummary?.Price?.RegularMarketPrice?.Raw;
            if (price.HasValue)
            {
                return (price.Value.ToString("C"), $"https://finance.yahoo.com/quote/{ticker}");
            }
        }
        catch (Exception)
        {
        }
        
        return null;
    }

    private static string FormatRevenue(long revenue)
    {
        if (revenue >= 1_000_000_000_000)
            return $"${revenue / 1_000_000_000_000.0:F1}B";
        if (revenue >= 1_000_000_000)
            return $"${revenue / 1_000_000_000.0:F1}B";
        if (revenue >= 1_000_000)
            return $"${revenue / 1_000_000.0:F1}M";
        return revenue.ToString("C");
    }
}

internal class YahooFinanceResponse
{
    public QuoteSummary? QuoteSummary { get; set; }
}

internal class QuoteSummary
{
    public FinancialData? FinancialData { get; set; }
    public PriceData? Price { get; set; }
}

internal class FinancialData
{
    public TotalRevenueData? TotalRevenue { get; set; }
}

internal class TotalRevenueData
{
    public long? Raw { get; set; }
}

internal class PriceData
{
    public RegularMarketPriceData? RegularMarketPrice { get; set; }
}

internal class RegularMarketPriceData
{
    public decimal? Raw { get; set; }
}