using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Playwright;
using System.Net;
using static Vke.E2e.Tests.TestResults;

namespace Vke.E2e.Tests;

public class BrowserTests : IAsyncLifetime, IDisposable
{
    private readonly List<string> _testVaultPaths = new();
    private IPlaywright? _playwright;
    private IBrowser? _browser;
    private WebApplication? _app;
    private Task? _appTask;

    public async Task InitializeAsync()
    {
        var testVaultPath = Path.Combine(Path.GetTempPath(), $"vke_test_{Guid.NewGuid()}");
        _testVaultPaths.Add(testVaultPath);
        Directory.CreateDirectory(testVaultPath);
        
        var envPath = Path.Combine(Directory.GetCurrentDirectory(), ".env");
        if (System.IO.File.Exists(envPath))
        {
            foreach (var line in System.IO.File.ReadAllLines(envPath))
            {
                var parts = line.Split('=', 2);
                if (parts.Length == 2 && !string.IsNullOrWhiteSpace(parts[0]))
                {
                    Environment.SetEnvironmentVariable(parts[0].Trim(), parts[1].Trim());
                }
            }
        }
        
        var vaultPath = Path.Combine(testVaultPath, "vault");
        Directory.CreateDirectory(vaultPath);
        Directory.CreateDirectory(Path.Combine(vaultPath, "raw"));
        Directory.CreateDirectory(Path.Combine(vaultPath, "wiki"));
        
        var builder = WebApplication.CreateBuilder(new[] { "--urls", "http://localhost:5050" });
        builder.Environment.ContentRootPath = Directory.GetCurrentDirectory();
        
        builder.WebHost.UseKestrel(options =>
        {
            options.Listen(IPAddress.Loopback, 5050);
        });
        
        var dbPath = Path.Combine(vaultPath, "vke.duckdb");
        var rawPath = Path.Combine(vaultPath, "raw");
        var wikiPath = Path.Combine(vaultPath, "wiki");

        builder.Services.AddSingleton<IngestTestServices>();

        var app = builder.Build();

        app.MapGet("/", () => TestResults.Redirect("/index.html"));
        app.MapGet("/index.html", () => TestResults.Text(GetHtml(), "text/html"));
        
        app.MapPost("/api/ingest", async (HttpContext ctx) =>
        {
            var start = DateTime.UtcNow;
            var logFile = Path.Combine(testVaultPath, "test.log");
            await System.IO.File.AppendAllTextAsync(logFile, $"[/api/ingest] START {start:HH:mm:ss.fff}\n");
            
            var body = await ctx.Request.ReadFromJsonAsync<IngestRequest>();
            if (string.IsNullOrEmpty(body?.Url))
                return TestResults.BadRequest(new { error = "URL required" });

            var sourceType = body.Type ?? "generic";
            var domain = body.Domain ?? "news";
            await System.IO.File.AppendAllTextAsync(logFile, $"[/api/ingest] URL={body.Url}, type={sourceType}, domain={domain}\n");

            try
            {
                await System.IO.File.AppendAllTextAsync(logFile, $"[/api/ingest] Creating services... elapsed={DateTime.UtcNow-start:HH:mm:ss.fff}\n");
                using var db = new Vke.Core.Data.VkeDbContext(dbPath);
                db.InitializeDatabase();

                var apiKey = Environment.GetEnvironmentVariable("ANTHROPIC_AUTH_TOKEN") ?? "";
                var baseUrl = Environment.GetEnvironmentVariable("ANTHROPIC_BASE_URL") ?? "https://api.minimax.io/anthropic";
                var model = Environment.GetEnvironmentVariable("ANTHROPIC_MODEL") ?? "MiniMax-M2.7-highspeed";

                await System.IO.File.AppendAllTextAsync(logFile, $"[/api/ingest] API: baseUrl={baseUrl}, model={model}, tokenSet={!string.IsNullOrEmpty(apiKey)}\n");

                var http = new HttpClient();
                http.Timeout = TimeSpan.FromMinutes(5);
                var llm = new Vke.Core.Services.LlmClient(http, baseUrl, model, apiKey);
                var secEdgar = new Vke.Core.Services.SecEdgarClient(http);
                var semScholar = new Vke.Core.Services.SemanticScholarClient(http);
                var genericUrl = new Vke.Core.Services.GenericUrlClient(http);
                var webSearch = new Vke.Core.Services.WebSearchClient(http);

                var ingestAgent = new Vke.Core.Agents.IngestAgent(db, llm, secEdgar, semScholar, genericUrl);
                var wikiGen = new Vke.Core.Services.WikiGenerator();
                var verifyAgent = new Vke.Core.Agents.VerifyAgent(db, llm, wikiGen, webSearch, wikiPath);

                await System.IO.File.AppendAllTextAsync(logFile, $"[/api/ingest] Calling IngestAsync... elapsed={DateTime.UtcNow-start:HH:mm:ss.fff}\n");
                var (sourceId, claims) = await ingestAgent.IngestAsync(body.Url, sourceType, domain);
                await System.IO.File.AppendAllTextAsync(logFile, $"[/api/ingest] IngestAsync done, {claims.Count} claims. elapsed={DateTime.UtcNow-start:HH:mm:ss.fff}\n");
                
                await System.IO.File.AppendAllTextAsync(logFile, $"[/api/ingest] Calling VerifyAndStoreAsync... elapsed={DateTime.UtcNow-start:HH:mm:ss.fff}\n");
                var result = await verifyAgent.VerifyAndStoreAsync(sourceId, claims);
                await System.IO.File.AppendAllTextAsync(logFile, $"[/api/ingest] DONE {DateTime.UtcNow:HH:mm:ss.fff}, total={DateTime.UtcNow-start:HH:mm:ss.fff}\n");

                return TestResults.Json(new
                {
                    sourceId,
                    verified = result.Verified,
                    corrected = result.Corrected,
                    falseCount = result.False,
                    disputed = result.Disputed,
                    unverifiable = result.Unverifiable
                });
            }
            catch (Exception ex)
            {
                await System.IO.File.AppendAllTextAsync(logFile, $"[/api/ingest] ERROR after {DateTime.UtcNow-start:HH:mm:ss.fff}: {ex.GetType().Name}: {ex.Message}\n{ex.StackTrace}\n");
                return TestResults.BadRequest(new { error = ex.Message });
            }
        });

        app.MapGet("/api/sources", () =>
        {
            try
            {
                using var db = new Vke.Core.Data.VkeDbContext(dbPath);
                db.InitializeDatabase();

                var sources = db.GetAllSources(20).Select(s => new
                {
                    s.Id,
                    s.Url,
                    s.Title,
                    s.SourceType,
                    FetchedAt = s.FetchedAt.ToString("o")
                }).ToList();

                return TestResults.Json(sources);
            }
            catch
            {
                return TestResults.Json(Array.Empty<object>());
            }
        });

        app.MapGet("/api/raw/{id}", (string id) =>
        {
            var filePath = Path.Combine(rawPath, $"{id}.md");
            if (!System.IO.File.Exists(filePath))
                return TestResults.NotFound();

            return TestResults.File(filePath, "text/plain");
        });

        _app = app;
        _appTask = app.RunAsync();
        
        await Task.Delay(500);
        
        _playwright = await Microsoft.Playwright.Playwright.CreateAsync();
        _browser = await _playwright.Chromium.LaunchAsync(new BrowserTypeLaunchOptions { Headless = true });
    }

    private string GetHtml()
    {
        return @"<!DOCTYPE html>
<html lang=""en"">
<head>
  <meta charset=""UTF-8"">
  <meta name=""viewport"" content=""width=device-width, initial-scale=1.0"">
  <title>VKE - Verified Knowledge Engine</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0a; color: #e5e5e5; min-height: 100vh; }
    .container { max-width: 800px; margin: 0 auto; padding: 2rem; }
    h1 { font-size: 1.5rem; font-weight: 600; margin-bottom: 0.5rem; color: #fff; }
    .subtitle { color: #737373; font-size: 0.875rem; margin-bottom: 2rem; }
    .card { background: #171717; border: 1px solid #262626; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; }
    .form-group { margin-bottom: 1rem; }
    label { display: block; font-size: 0.75rem; font-weight: 500; color: #a3a3a3; margin-bottom: 0.5rem; text-transform: uppercase; letter-spacing: 0.05em; }
    input, select { width: 100%; padding: 0.75rem; background: #0a0a0a; border: 1px solid #262626; border-radius: 6px; color: #e5e5e5; font-size: 0.875rem; }
    input:focus, select:focus { outline: none; border-color: #52525b; }
    button { width: 100%; padding: 0.75rem; background: #fff; color: #0a0a0a; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 0.875rem; }
    button:hover { background: #e5e5e5; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    .sources { margin-top: 2rem; }
    .source-item { background: #171717; border: 1px solid #262626; border-radius: 8px; padding: 1rem; margin-bottom: 0.75rem; cursor: pointer; transition: border-color 0.15s; }
    .source-item:hover { border-color: #52525b; }
    .source-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem; }
    .source-title { font-weight: 500; color: #fff; font-size: 0.875rem; }
    .source-meta { font-size: 0.75rem; color: #737373; }
    .raw-content { margin-top: 1rem; padding: 1rem; background: #0a0a0a; border-radius: 6px; font-family: monospace; font-size: 0.8rem; white-space: pre-wrap; word-break: break-word; max-height: 400px; overflow-y: auto; display: none; }
    .raw-content.visible { display: block; }
    .empty { text-align: center; padding: 3rem; color: #52525b; }
    .error { background: #7f1d1d; border-color: #991b1b; color: #fca5a5; }
    .success { background: #14532d; border-color: #166534; color: #86efac; }
    .message { margin-top: 1rem; padding: 1rem; border-radius: 6px; display: none; }
    .message.visible { display: block; }
  </style>
</head>
<body>
  <div class=""container"">
    <h1>VKE</h1>
    <p class=""subtitle"">Verified Knowledge Engine</p>

    <div class=""card"">
      <form id=""ingest-form"">
        <div class=""form-group"">
          <label>URL</label>
          <input type=""url"" id=""url"" placeholder=""https://..."" required>
        </div>
        <div style=""display: flex; gap: 1rem;"">
          <div class=""form-group"" style=""flex: 1;"">
            <label>Type</label>
            <select id=""type"">
              <option value=""generic"">Generic</option>
              <option value=""sec_10k"">SEC 10-K</option>
              <option value=""preprint"">Preprint</option>
            </select>
          </div>
          <div class=""form-group"" style=""flex: 1;"">
            <label>Domain</label>
            <select id=""domain"">
              <option value=""news"">News</option>
              <option value=""academic"">Academic</option>
              <option value=""financial"">Financial</option>
              <option value=""social"">Social</option>
            </select>
          </div>
        </div>
        <button type=""submit"" id=""submit-btn"">Ingest</button>
        <div id=""message"" class=""message""></div>
      </form>
    </div>

    <div class=""sources"">
      <h2 style=""font-size: 1rem; font-weight: 500; margin-bottom: 1rem; color: #a3a3a3;"">Recent Sources</h2>
      <div id=""sources-list"">
        <div class=""empty"">No sources yet. Ingest your first URL.</div>
      </div>
    </div>
  </div>

  <script>
    let sources = [];

    async function loadSources() {
      try {
        const res = await fetch('/api/sources');
        if (res.ok) {
          sources = await res.json();
          renderSources();
        }
      } catch (e) {
        console.error('Failed to load sources');
      }
    }

    function renderSources() {
      const list = document.getElementById('sources-list');
      if (sources.length === 0) {
        list.innerHTML = '<div class=""empty"">No sources yet. Ingest your first URL.</div>';
        return;
      }
      list.innerHTML = sources.map(s => {
        const title = s.title || s.url;
        const meta = s.sourceType + ' · ' + new Date(s.fetchedAt).toLocaleDateString();
        return '<div class=""source-item"" onclick=""toggleSource(' + s.id + ')""><div class=""source-header""><div><div class=""source-title"">' + title + '</div><div class=""source-meta"">' + meta + '</div></div></div><div id=""raw-' + s.id + '"" class=""raw-content""></div></div>';
      }).join('');
    }

    async function toggleSource(id) {
      const el = document.getElementById('raw-' + id);
      if (el.classList.contains('visible')) {
        el.classList.remove('visible');
        return;
      }
      el.classList.add('visible');
      const res = await fetch('/api/raw/' + id);
      if (res.ok) {
        const text = await res.text();
        el.textContent = text;
      }
    }

    document.getElementById('ingest-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('submit-btn');
      const msg = document.getElementById('message');
      btn.disabled = true;
      btn.textContent = 'Ingesting...';
      msg.classList.remove('visible', 'error', 'success');

      try {
        const res = await fetch('/api/ingest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url: document.getElementById('url').value,
            type: document.getElementById('type').value,
            domain: document.getElementById('domain').value
          })
        });

        const data = await res.json();
        if (res.ok) {
          msg.className = 'message success visible';
          msg.textContent = 'Ingested: ' + data.verified + ' verified, ' + data.falseCount + ' false';
          document.getElementById('url').value = '';
          await loadSources();
        } else {
          msg.className = 'message error visible';
          msg.textContent = 'Error: ' + data.error;
        }
      } catch (e) {
        msg.className = 'message error visible';
        msg.textContent = 'Failed: ' + e.message;
      }

      btn.disabled = false;
      btn.textContent = 'Ingest';
    });

    loadSources();
  </script>
</body>
</html>";
    }

    [Fact]
    public async Task IngestArxivPaper()
    {
        var context = await _browser!.NewContextAsync();
        var page = await context.NewPageAsync();
        
        await page.GotoAsync("http://localhost:5050");
        
        await page.FillAsync("#url", "https://arxiv.org/pdf/2309.06180");
        await page.SelectOptionAsync("#type", "generic");
        await page.SelectOptionAsync("#domain", "academic");
        await page.ClickAsync("#submit-btn");
        
        await page.WaitForSelectorAsync(".success", new PageWaitForSelectorOptions { Timeout = 120000 });
        
        var sourcesText = await page.TextContentAsync("#sources-list");
        Assert.NotNull(sourcesText);
        
        await context.CloseAsync();
    }

    [Fact]
    public async Task ViewRawContent()
    {
        var context = await _browser!.NewContextAsync();
        var page = await context.NewPageAsync();
        
        await page.GotoAsync("http://localhost:5050");
        
        await page.FillAsync("#url", "https://arxiv.org/pdf/2309.06180");
        await page.SelectOptionAsync("#type", "generic");
        await page.SelectOptionAsync("#domain", "academic");
        await page.ClickAsync("#submit-btn");
        
        await page.WaitForSelectorAsync(".success", new PageWaitForSelectorOptions { Timeout = 120000 });
        
        var sources = await page.QuerySelectorAllAsync(".source-item");
        Assert.NotEmpty(sources);
        
        await sources[0].ClickAsync();
        await page.WaitForSelectorAsync(".raw-content.visible", new PageWaitForSelectorOptions { Timeout = 30000 });
        
        var rawContent = await page.TextContentAsync(".raw-content.visible");
        Assert.NotNull(rawContent);
        Assert.NotEmpty(rawContent);
        
        await context.CloseAsync();
    }

    [Fact]
    public async Task MultipleIngestions()
    {
        var context = await _browser!.NewContextAsync();
        var page = await context.NewPageAsync();
        
        await page.GotoAsync("http://localhost:5050");
        
        await page.FillAsync("#url", "https://arxiv.org/pdf/2309.06180");
        await page.SelectOptionAsync("#type", "generic");
        await page.SelectOptionAsync("#domain", "academic");
        await page.ClickAsync("#submit-btn");
        await page.WaitForSelectorAsync(".success", new PageWaitForSelectorOptions { Timeout = 120000 });
        
        await page.FillAsync("#url", "https://arxiv.org/pdf/2510.18518");
        await page.SelectOptionAsync("#type", "preprint");
        await page.SelectOptionAsync("#domain", "academic");
        await page.ClickAsync("#submit-btn");
        await page.WaitForSelectorAsync(".success", new PageWaitForSelectorOptions { Timeout = 120000 });
        
        var sources = await page.QuerySelectorAllAsync(".source-item");
        Assert.True(sources.Count >= 2, $"Expected at least 2 sources, got {sources.Count}");
        
        await context.CloseAsync();
    }

    [Fact]
    public async Task IngestNewsArticle()
    {
        var context = await _browser!.NewContextAsync();
        var page = await context.NewPageAsync();
        
        await page.GotoAsync("http://localhost:5050");
        
        await page.FillAsync("#url", "https://arxiv.org/pdf/2309.06180");
        await page.SelectOptionAsync("#type", "generic");
        await page.SelectOptionAsync("#domain", "academic");
        await page.ClickAsync("#submit-btn");
        
        await page.WaitForSelectorAsync(".success", new PageWaitForSelectorOptions { Timeout = 120000 });
        
        var sourcesText = await page.TextContentAsync("#sources-list");
        Assert.NotNull(sourcesText);
        
        var sources = await page.QuerySelectorAllAsync(".source-item");
        Assert.NotEmpty(sources);
        
        await context.CloseAsync();
    }

    public async Task DisposeAsync()
    {
        if (_browser != null)
            await _browser.CloseAsync();
        _browser = null;
        _playwright?.Dispose();
        _playwright = null;
        
        if (_app != null)
        {
            await _app.StopAsync();
        }
        
        foreach (var path in _testVaultPaths)
        {
            if (Directory.Exists(path))
                Directory.Delete(path, recursive: true);
        }
    }

    public void Dispose()
    {
        foreach (var path in _testVaultPaths)
        {
            if (Directory.Exists(path))
                Directory.Delete(path, recursive: true);
        }
    }
}

public class IngestTestServices
{
}

public record IngestRequest(string? Url, string? Type, string? Domain);

public static class TestResults
{
    public static IResult Html(string html) => new HtmlResult(html);
    public static IResult Json(object? obj) => new JsonResult(obj);
    public static IResult BadRequest(object? obj) => new BadRequestResult(obj);
    public static IResult NotFound() => new NotFoundResult();
    public static IResult File(string path, string contentType) => new TestFileResult(path, contentType);
    public static IResult Redirect(string url) => new TestRedirectResult(url);
    public static IResult Text(string content, string contentType) => new TextResult(content, contentType);
}

public class HtmlResult : IResult
{
    private readonly string _html;
    public HtmlResult(string html) => _html = html;
    public Task ExecuteAsync(HttpContext context)
    {
        context.Response.ContentType = "text/html";
        return context.Response.WriteAsync(_html);
    }
}

public class TextResult : IResult
{
    private readonly string _content;
    private readonly string _contentType;
    public TextResult(string content, string contentType) => (_content, _contentType) = (content, contentType);
    public Task ExecuteAsync(HttpContext context)
    {
        context.Response.ContentType = _contentType;
        return context.Response.WriteAsync(_content);
    }
}

public class JsonResult : IResult
{
    private readonly object _obj;
    public JsonResult(object obj) => _obj = obj;
    public Task ExecuteAsync(HttpContext context)
    {
        context.Response.ContentType = "application/json";
        return context.Response.WriteAsJsonAsync(_obj);
    }
}

public class BadRequestResult : IResult
{
    private readonly object? _obj;
    public BadRequestResult(object? obj) => _obj = obj;
    public Task ExecuteAsync(HttpContext context)
    {
        context.Response.StatusCode = 400;
        context.Response.ContentType = "application/json";
        return context.Response.WriteAsJsonAsync(_obj);
    }
}

public class NotFoundResult : IResult
{
    public Task ExecuteAsync(HttpContext context)
    {
        context.Response.StatusCode = 404;
        return Task.CompletedTask;
    }
}

public class TestFileResult : IResult
{
    private readonly string _path;
    private readonly string _contentType;
    public TestFileResult(string path, string contentType) => (_path, _contentType) = (path, contentType);
    public Task ExecuteAsync(HttpContext context)
    {
        context.Response.ContentType = _contentType;
        return context.Response.SendFileAsync(_path);
    }
}

public class TestRedirectResult : IResult
{
    private readonly string _url;
    public TestRedirectResult(string url) => _url = url;
    public Task ExecuteAsync(HttpContext context)
    {
        context.Response.StatusCode = 302;
        context.Response.Headers["Location"] = _url;
        return Task.CompletedTask;
    }
}
