using Vke.Core.Data;
using Vke.Core.Data.Models;
using Vke.Core.Services;

var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

var vaultBase = Environment.GetEnvironmentVariable("OBSIDIAN_VAULT_PATH") ?? Path.Combine(Directory.GetCurrentDirectory(), "vault");
var dbPath = Path.Combine(vaultBase, "vke.duckdb");
var rawPath = Path.Combine(vaultBase, "raw");
var wikiPath = Path.Combine(vaultBase, "wiki");

Directory.CreateDirectory(Path.GetDirectoryName(dbPath)!);
Directory.CreateDirectory(rawPath);
Directory.CreateDirectory(wikiPath);

app.MapGet("/", () => VkeResults.Redirect("/index.html"));

app.MapGet("/index.html", () => VkeResults.Html(GetHtml()));

app.MapPost("/api/ingest", async (HttpContext ctx) =>
{
    var body = await ctx.Request.ReadFromJsonAsync<IngestRequest>();
    if (string.IsNullOrEmpty(body?.Url))
        return VkeResults.BadRequest(new { error = "URL required" });

    var sourceType = body.Type ?? "generic";
    var domain = body.Domain ?? "news";

    try
    {
        using var db = new VkeDbContext(dbPath);
        db.InitializeDatabase();

        var baseUrl = Environment.GetEnvironmentVariable("ANTHROPIC_BASE_URL") ?? "https://api.minimax.io/anthropic";
        var model = Environment.GetEnvironmentVariable("ANTHROPIC_MODEL") ?? "MiniMax-M2.7-highspeed";
        using var http = new HttpClient();
        http.Timeout = TimeSpan.FromMinutes(5);
        var llm = new LlmClient(http, baseUrl, model);
        var secEdgar = new SecEdgarClient(http);
        var semScholar = new SemanticScholarClient(http);
        var genericUrl = new GenericUrlClient(http);

        var ingestAgent = new Vke.Core.Agents.IngestAgent(db, llm, secEdgar, semScholar, genericUrl);
        var wikiGen = new Vke.Core.Services.WikiGenerator();
        var verifyAgent = new Vke.Core.Agents.VerifyAgent(db, llm, wikiGen, wikiPath);

        var (sourceId, claims) = await ingestAgent.IngestAsync(body.Url, sourceType, domain);
        var result = await verifyAgent.VerifyAndStoreAsync(sourceId, claims);

        return Results.Json(new
        {
            sourceId,
            verified = result.Verified,
            corrected = result.Corrected,
            falseCount = result.False,
            disputed = result.Disputed,
            unverifiable = result.Unverifiable
        });
    }
    catch (ArgumentException)
    {
        return VkeResults.BadRequest(new { error = "Invalid request parameters" });
    }
    catch (InvalidOperationException)
    {
        return VkeResults.BadRequest(new { error = "Operation failed" });
    }
    catch (Exception)
    {
        return VkeResults.BadRequest(new { error = "An internal error occurred. Please try again." });
    }
});

app.MapGet("/api/sources", () =>
{
    try
    {
        using var db = new VkeDbContext(dbPath);
        db.InitializeDatabase();

        var sources = db.GetAllSources(20).Select(s => new
        {
            s.Id,
            s.Url,
            s.Title,
            s.SourceType,
            FetchedAt = s.FetchedAt.ToString("o")
        }).ToList();

        return VkeResults.Json(sources);
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"Failed to load sources: {ex.Message}");
        return VkeResults.Json(Array.Empty<object>());
    }
});

app.MapGet("/api/raw/{id}", (string id) =>
{
    var filePath = Path.Combine(rawPath, $"{id}.md");
    try
    {
        return VkeResults.File(filePath, "text/plain");
    }
    catch (FileNotFoundException)
    {
        return VkeResults.NotFound();
    }
});

app.Run();

static string GetHtml()
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

public record IngestRequest(string? Url, string? Type, string? Domain);

public static class VkeResults
{
    public static IResult Html(string html) => new HtmlResult(html);
    public static IResult Json(object? obj) => new JsonResult(obj);
    public static IResult BadRequest(object? obj) => new BadRequestResult(obj);
    public static IResult NotFound() => new NotFoundResult();
    public static IResult File(string path, string contentType) => new FileResult(path, contentType);
    public static IResult Redirect(string url) => new RedirectResult(url);
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

public class FileResult : IResult
{
    private readonly string _path;
    private readonly string _contentType;
    public FileResult(string path, string contentType) => (_path, _contentType) = (path, contentType);
    public Task ExecuteAsync(HttpContext context)
    {
        context.Response.ContentType = _contentType;
        return context.Response.SendFileAsync(_path);
    }
}

public class RedirectResult : IResult
{
    private readonly string _url;
    public RedirectResult(string url) => _url = url;
    public Task ExecuteAsync(HttpContext context)
    {
        context.Response.StatusCode = 302;
        context.Response.Headers["Location"] = _url;
        return Task.CompletedTask;
    }
}
