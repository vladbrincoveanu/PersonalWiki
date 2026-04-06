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

    private Task ScanFolderAsync(string folderPath, string folder, VkeDbContext db)
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
        
        return Task.CompletedTask;
    }

    public static string ComputeFileId(string filePath, string folder)
    {
        using var sha = System.Security.Cryptography.SHA256.Create();
        var input = $"{folder}:{filePath}";
        var hash = sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(hash)[..16].ToLowerInvariant();
    }
}
