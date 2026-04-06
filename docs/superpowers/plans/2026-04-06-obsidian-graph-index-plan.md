# Obsidian Graph Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unified Obsidian graph index that scans /openclaw/research/{raw,interesting,trusted} folders, creates wiki-links between pages, and auto-updates index.md after every ingest.

**Architecture:** Scanner indexes files from folder hierarchy into DuckDB. WikiGenerator enhanced to use [[wiki-links]]. IndexGenerator creates unified index.md. All components triggered after ingest/lint/correct commands.

**Tech Stack:** C# .NET 10, DuckDB.NET, existing VkeDbContext, WikiGenerator

---

## File Structure

**New files:**
- `src/Vke.Core/Services/FileScanner.cs` - Scans {raw,interesting,trusted} folders
- `src/Vke.Core/Services/IndexGenerator.cs` - Generates index.md
- `src/Vke.Core/Data/Models/RawFile.cs` - Model for raw_files table

**Modified files:**
- `src/Vke.Core/Data/VkeDbContext.cs` - Add raw_files table and queries
- `src/Vke.Core/Services/WikiGenerator.cs` - Add wiki-links between pages
- `src/Vke.Cli/Program.cs` - Call UpdateIndexAsync after ingest/lint/correct

---

### Task 1: Add raw_files table to VkeDbContext

**Files:**
- Modify: `src/Vke.Core/Data/VkeDbContext.cs:1-50`

- [ ] **Step 1: Add raw_files table creation to InitializeDatabase**

Add after existing CREATE TABLE statements (around line 78):

```csharp
cmd.CommandText = @"
    CREATE TABLE IF NOT EXISTS raw_files (
        id              TEXT PRIMARY KEY,
        filename        TEXT NOT NULL,
        full_path       TEXT NOT NULL,
        folder          TEXT NOT NULL,
        file_type       TEXT,
        size_bytes      BIGINT,
        modified_at     TIMESTAMP,
        indexed_at      TIMESTAMP DEFAULT now(),
        linked_entity   TEXT,
        linked_source   TEXT,
        status          TEXT DEFAULT 'pending'
    );
";
cmd.ExecuteNonQuery();
```

- [ ] **Step 2: Add methods for raw_files CRUD**

Add to VkeDbContext.cs:

```csharp
public void InsertRawFile(RawFile file)
{
    using var cmd = _connection.CreateCommand();
    cmd.CommandText = @"
        INSERT INTO raw_files (id, filename, full_path, folder, file_type, size_bytes, modified_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            modified_at = excluded.modified_at,
            size_bytes = excluded.size_bytes,
            status = excluded.status
    ";
    cmd.Parameters.Add(new DuckDBParameter(file.Id));
    cmd.Parameters.Add(new DuckDBParameter(file.Filename));
    cmd.Parameters.Add(new DuckDBParameter(file.FullPath));
    cmd.Parameters.Add(new DuckDBParameter(file.Folder));
    cmd.Parameters.Add(new DuckDBParameter(file.FileType ?? (object)DBNull.Value));
    cmd.Parameters.Add(new DuckDBParameter(file.SizeBytes));
    cmd.Parameters.Add(new DuckDBParameter(file.ModifiedAt));
    cmd.Parameters.Add(new DuckDBParameter(file.Status));
    cmd.ExecuteNonQuery();
}

public List<RawFile> GetRawFiles(string? folder = null)
{
    var files = new List<RawFile>();
    using var cmd = _connection.CreateCommand();
    cmd.CommandText = folder == null
        ? "SELECT * FROM raw_files ORDER BY folder, filename"
        : "SELECT * FROM raw_files WHERE folder = ? ORDER BY filename";
    if (folder != null)
        cmd.Parameters.Add(new DuckDBParameter(folder));
    
    using var reader = cmd.ExecuteReader();
    while (reader.Read())
    {
        files.Add(new RawFile
        {
            Id = reader.GetString(0),
            Filename = reader.GetString(1),
            FullPath = reader.GetString(2),
            Folder = reader.GetString(3),
            FileType = reader.IsDBNull(4) ? null : reader.GetString(4),
            SizeBytes = reader.IsDBNull(5) ? null : reader.GetInt64(5),
            ModifiedAt = reader.IsDBNull(6) ? null : reader.GetDateTime(6),
            IndexedAt = reader.GetDateTime(7),
            LinkedEntity = reader.IsDBNull(8) ? null : reader.GetString(8),
            LinkedSource = reader.IsDBNull(9) ? null : reader.GetString(9),
            Status = reader.GetString(10)
        });
    }
    return files;
}

public void UpdateRawFileStatus(string id, string status, string? linkedEntity = null, string? linkedSource = null)
{
    using var cmd = _connection.CreateCommand();
    cmd.CommandText = @"
        UPDATE raw_files 
        SET status = ?, linked_entity = ?, linked_source = ?
        WHERE id = ?
    ";
    cmd.Parameters.Add(new DuckDBParameter(status));
    cmd.Parameters.Add(new DuckDBParameter(linkedEntity ?? (object)DBNull.Value));
    cmd.Parameters.Add(new DuckDBParameter(linkedSource ?? (object)DBNull.Value));
    cmd.Parameters.Add(new DuckDBParameter(id));
    cmd.ExecuteNonQuery();
}
```

- [ ] **Step 3: Build to verify**

Run: `dotnet build src/Vke.Core/Vke.Core.csproj`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add src/Vke.Core/Data/VkeDbContext.cs
git commit -m "feat: add raw_files table to VkeDbContext"
```

---

### Task 2: Create RawFile model

**Files:**
- Create: `src/Vke.Core/Data/Models/RawFile.cs`

- [ ] **Step 1: Create RawFile model**

```csharp
namespace Vke.Core.Data.Models;

public class RawFile
{
    public string Id { get; set; } = "";
    public string Filename { get; set; } = "";
    public string FullPath { get; set; } = "";
    public string Folder { get; set; } = "";  // raw, interesting, trusted
    public string? FileType { get; set; }
    public long? SizeBytes { get; set; }
    public DateTime? ModifiedAt { get; set; }
    public DateTime IndexedAt { get; set; }
    public string? LinkedEntity { get; set; }
    public string? LinkedSource { get; set; }
    public string Status { get; set; } = "pending";  // pending, processed, verified
}
```

- [ ] **Step 2: Build to verify**

Run: `dotnet build src/Vke.Core/Vke.Core.csproj`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add src/Vke.Core/Data/Models/RawFile.cs
git commit -m "feat: add RawFile model"
```

---

### Task 3: Create FileScanner service

**Files:**
- Create: `src/Vke.Core/Services/FileScanner.cs`

- [ ] **Step 1: Create FileScanner class**

```csharp
using Vke.Core.Data;
using Vke.Core.Data.Models;

namespace Vke.Core.Services;

public class FileScanner
{
    private readonly string[] _folders = { "raw", "interesting", "trusted" };
    
    public async Task ScanAndIndexAsync(string basePath, VkeDbContext db)
    {
        foreach (var folder in _folders)
        {
            var folderPath = Path.Combine(basePath, folder);
            if (!Directory.Exists(folderPath))
                continue;

            await ScanFolderAsync(folderPath, folder, db);
        }
    }

    private async Task ScanFolderAsync(string folderPath, string folder, VkeDbContext db)
    {
        var files = Directory.GetFiles(folderPath, "*", SearchOption.AllDirectories);
        
        foreach (var filePath in files)
        {
            var fileInfo = new FileInfo(filePath);
            var id = ComputeFileId(filePath, folder);
            
            var rawFile = new RawFile
            {
                Id = id,
                Filename = fileInfo.Name,
                FullPath = filePath,
                Folder = folder,
                FileType = fileInfo.Extension.TrimStart('.').ToLowerInvariant(),
                SizeBytes = fileInfo.Length,
                ModifiedAt = fileInfo.LastWriteTimeUtc,
                IndexedAt = DateTime.UtcNow,
                Status = "pending"
            };
            
            db.InsertRawFile(rawFile);
        }
    }

    public static string ComputeFileId(string filePath, string folder)
    {
        using var sha = System.Security.Cryptography.SHA256.Create();
        var input = $"{folder}:{filePath}";
        var hash = sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(hash)[..16].ToLowerInvariant();
    }
}
```

- [ ] **Step 2: Build to verify**

Run: `dotnet build src/Vke.Core/Vke.Core.csproj`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add src/Vke.Core/Services/FileScanner.cs
git commit -m "feat: add FileScanner to index raw/interesting/trusted folders"
```

---

### Task 4: Enhance WikiGenerator with wiki-links

**Files:**
- Modify: `src/Vke.Core/Services/WikiGenerator.cs`

- [ ] **Step 1: Update GenerateEntityPage to include source wiki-links**

In `GenerateEntityPage`, after the claims sections (around line 65), add:

```csharp
// Add source links if claims have source IDs
var sourceIds = claims.Select(c => c.SourceId).Distinct().ToList();
if (sourceIds.Any())
{
    md += "## Sources\n";
    foreach (var sourceId in sourceIds)
        md += $"- [[sources/{sourceId}.md|Source {sourceId}]]\n";
    md += "\n";
}
```

- [ ] **Step 2: Update GenerateSourcePage to include wiki-links to entities and raw file**

In `GenerateSourcePage` (around line 106), add after the claims section:

```csharp
// Add entity links if claims have entities
var entityNames = claims.Select(c => c.Normalized.Split(':')[0]).Distinct().ToList();
if (entityNames.Any())
{
    md += "## Entities\n";
    foreach (var entity in entityNames)
        md += $"- [[entities/{ToFileName(entity)}.md|{entity}]]\n";
    md += "\n";
}

// Add raw file link if available
if (!string.IsNullOrEmpty(source.Url))
{
    var rawFile = claims.FirstOrDefault()?.Source?.Url;
    if (!string.IsNullOrEmpty(rawFile))
    {
        var fileName = Path.GetFileName(rawFile);
        var folder = GetFolderForUrl(rawFile);
        md += $"## Raw Source\n- [[{folder}/{fileName}|{fileName}]]\n\n";
    }
}
```

- [ ] **Step 3: Add helper method GetFolderForUrl**

Add at end of class:

```csharp
private static string GetFolderForUrl(string url)
{
    if (url.Contains("/sec.gov/") || url.Contains("/arxiv.org/"))
        return "raw";
    if (url.Contains("/semanticscholar.org/"))
        return "interesting";
    return "raw";
}
```

- [ ] **Step 4: Build to verify**

Run: `dotnet build src/Vke.Core/Vke.Core.csproj`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add src/Vke.Core/Services/WikiGenerator.cs
git commit -m "feat: add wiki-links to WikiGenerator for Obsidian graph"
```

---

### Task 5: Create IndexGenerator service

**Files:**
- Create: `src/Vke.Core/Services/IndexGenerator.cs`

- [ ] **Step 1: Create IndexGenerator class**

```csharp
using Vke.Core.Data;
using Vke.Core.Data.Models;

namespace Vke.Core.Services;

public class IndexGenerator
{
    public async Task GenerateIndexAsync(string basePath, VkeDbContext db)
    {
        var indexPath = Path.Combine(basePath, "index.md");
        var md = "# Research Vault Index\n\n";
        md += $"_Last updated: {DateTime.UtcNow:yyyy-MM-dd HH:mm:ss} UTC_\n\n";

        // Entities section
        md += "## Entities\n\n";
        var entities = GetEntitySummary(db);
        if (entities.Any())
        {
            md += "| Entity | Tier | Claims | Last Updated |\n";
            md += "|--------|------|--------|---------------|\n";
            foreach (var e in entities)
                md += $"| [[entities/{e.Key}.md|{e.Key}]] | {e.Tier} | {e.Count} | {e.LastUpdated:yyyy-MM-dd} |\n";
        }
        else
        {
            md += "_No entities yet._\n";
        }
        md += "\n";

        // Sources section
        md += "## Sources\n\n";
        var sources = GetSourceSummary(db);
        if (sources.Any())
        {
            md += "| Source | Type | Domain | Claims |\n";
            md += "|--------|------|--------|--------|\n";
            foreach (var s in sources)
                md += $"| [[sources/{s.Key}.md|{s.Key}]] | {s.Type} | {s.Domain} | {s.Count} |\n";
        }
        else
        {
            md += "_No sources yet._\n";
        }
        md += "\n";

        // Raw Files section
        md += "## Raw Files\n\n";
        var rawFiles = db.GetRawFiles("raw");
        if (rawFiles.Any())
        {
            md += "| File | Modified | Status |\n";
            md += "|------|----------|--------|\n";
            foreach (var f in rawFiles)
                md += $"| [[raw/{f.Filename}|{f.Filename}]] | {f.ModifiedAt?:d} | {f.Status} |\n";
        }
        else
        {
            md += "_No raw files indexed._\n";
        }
        md += "\n";

        // Interesting section
        md += "## Interesting\n\n";
        var interesting = db.GetRawFiles("interesting");
        if (interesting.Any())
        {
            md += "| File | Modified | Status |\n";
            md += "|------|----------|--------|\n";
            foreach (var f in interesting)
                md += $"| [[interesting/{f.Filename}|{f.Filename}]] | {f.ModifiedAt?:d} | {f.Status} |\n";
        }
        else
        {
            md += "_No interesting files indexed._\n";
        }
        md += "\n";

        // Trusted section
        md += "## Trusted\n\n";
        var trusted = db.GetRawFiles("trusted");
        if (trusted.Any())
        {
            md += "| File | Modified | Status |\n";
            md += "|------|----------|--------|\n";
            foreach (var f in trusted)
                md += $"| [[trusted/{f.Filename}|{f.Filename}]] | {f.ModifiedAt?:d} | {f.Status} |\n";
        }
        else
        {
            md += "_No trusted files indexed._\n";
        }

        try
        {
            await File.WriteAllTextAsync(indexPath, md);
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException($"Failed to write index to '{indexPath}'", ex);
        }
    }

    private List<(string Key, int Tier, int Count, DateTime LastUpdated)> GetEntitySummary(VkeDbContext db)
    {
        // Query claims grouped by entity
        var summary = new List<(string, int, int, DateTime)>();
        using var cmd = db.GetConnection().CreateCommand();
        cmd.CommandText = @"
            SELECT c.normalized, MIN(s.source_type), COUNT(*), MAX(c.last_verified)
            FROM claims c
            JOIN sources s ON c.source_id = s.id
            WHERE c.is_active = TRUE
            GROUP BY c.normalized
            ORDER BY c.normalized
        ";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            var entity = reader.GetString(0);
            var tier = GetTierForType(reader.GetString(1));
            var count = reader.GetInt32(2);
            var lastVerified = reader.IsDBNull(3) ? DateTime.MinValue : reader.GetDateTime(3);
            summary.Add((entity, tier, count, lastVerified));
        }
        return summary;
    }

    private List<(string Key, string Type, string Domain, int Count)> GetSourceSummary(VkeDbContext db)
    {
        var summary = new List<(string, string, string, int)>();
        using var cmd = db.GetConnection().CreateCommand();
        cmd.CommandText = @"
            SELECT s.id, s.source_type, s.domain, COUNT(c.id)
            FROM sources s
            LEFT JOIN claims c ON s.id = c.source_id AND c.is_active = TRUE
            WHERE s.is_active = TRUE
            GROUP BY s.id, s.source_type, s.domain
            ORDER BY s.fetched_at DESC
        ";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            var id = reader.GetString(0);
            var type = reader.GetString(1);
            var domain = reader.IsDBNull(2) ? "unknown" : reader.GetString(2);
            var count = reader.GetInt32(3);
            summary.Add((id, type, domain, count));
        }
        return summary;
    }

    private int GetTierForType(string sourceType)
    {
        return sourceType switch
        {
            "sec_10k" or "sec_10q" or "sec_8k" or "sec_proxy" => 1,
            "peer_reviewed" or "central_bank" => 1,
            "preprint" or "news_wire" or "sell_side" or "data_provider" => 2,
            "govt_stats" => 2,
            "news_article" or "conference_talk" or "company_blog" or "industry_report" => 3,
            "blog_post" or "social_media" or "anonymous" or "llm_generated" => 4,
            _ => 4
        };
    }
}
```

- [ ] **Step 2: Build to verify**

Run: `dotnet build src/Vke.Core/Vke.Core.csproj`
Expected: Build succeeds (may have warnings)

- [ ] **Step 3: Commit**

```bash
git add src/Vke.Core/Services/IndexGenerator.cs
git commit -m "feat: add IndexGenerator for unified obsidian index"
```

---

### Task 6: Wire up auto-update in CLI

**Files:**
- Modify: `src/Vke.Cli/Program.cs`

- [ ] **Step 1: Add FileScanner and IndexGenerator to CLI**

Add after line 36:
```csharp
var fileScanner = new FileScanner();
var indexGen = new IndexGenerator();
```

- [ ] **Step 2: Call ScanAndIndexAsync and GenerateIndexAsync after ingest command**

After line 73 (`Console.WriteLine($"Wiki written to: {wikiPath}/sources/ and {wikiPath}/entities/");`), add:

```csharp
Console.WriteLine("Scanning for new files...");
await fileScanner.ScanAndIndexAsync(vaultBase, db);
Console.WriteLine("Updating index...");
await indexGen.GenerateIndexAsync(vaultBase, db);
Console.WriteLine($"Index updated at {vaultBase}/index.md");
```

- [ ] **Step 3: Call ScanAndIndexAsync and GenerateIndexAsync after lint command**

After line 87 (after the lint output), add:

```csharp
Console.WriteLine("Scanning for new files...");
await fileScanner.ScanAndIndexAsync(vaultBase, db);
Console.WriteLine("Updating index...");
await indexGen.GenerateIndexAsync(vaultBase, db);
```

- [ ] **Step 4: Call ScanAndIndexAsync and GenerateIndexAsync after correct command**

After line 124 (after correction output), add before the break:

```csharp
Console.WriteLine("Scanning for new files...");
await fileScanner.ScanAndIndexAsync(vaultBase, db);
Console.WriteLine("Updating index...");
await indexGen.GenerateIndexAsync(vaultBase, db);
```

- [ ] **Step 5: Build to verify**

Run: `dotnet build src/Vke.Cli/Vke.Cli.csproj`
Expected: Build succeeds

- [ ] **Step 6: Commit**

```bash
git add src/Vke.Cli/Program.cs
git commit -m "feat: wire up auto-update index after ingest/lint/correct"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full build**

Run: `dotnet build Vke.sln`
Expected: 0 errors

- [ ] **Step 2: Run tests**

Run: `dotnet test Vke.sln`
Expected: All tests pass

- [ ] **Step 3: Push all commits**

```bash
git push
```

---

## Spec Coverage Check

- [x] Scanner indexes /openclaw/research/{raw,interesting,trusted} - Task 3
- [x] raw_files table in DuckDB - Task 1
- [x] WikiGenerator wiki-links between entity/source pages - Task 4
- [x] IndexGenerator creates index.md with all sections - Task 5
- [x] Auto-update after ingest/lint/correct - Task 6
- [x] LLM-friendly markdown format with wiki-links - Task 4, 5

## Plan Complete

Saved to: `docs/superpowers/plans/2026-04-06-obsidian-graph-index-plan.md`
