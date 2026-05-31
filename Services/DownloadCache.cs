using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

namespace AEPluginInstaller.Services;

/// <summary>
/// Постоянный кэш в %AppData%\AEPluginInstaller\cache. Ключ — Google Drive ID + ожидаемое
/// имя файла. Удаление — только вручную из настроек.
/// </summary>
public class DownloadCache
{
    public string CacheDir { get; }

    public DownloadCache()
    {
        CacheDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "AEPluginInstaller", "cache");
        Directory.CreateDirectory(CacheDir);
    }

    /// <summary>
    /// Возвращает путь к закэшированному файлу, если он есть. Имя ключа — sanitized fileId.
    /// Если задан expectedSize > 0, дополнительно проверяем размер.
    /// </summary>
    public string? TryGet(string fileId, string desiredFileName, long expectedSize = 0)
    {
        if (string.IsNullOrEmpty(fileId)) return null;
        var dir = Path.Combine(CacheDir, Sanitize(fileId));
        if (!Directory.Exists(dir)) return null;

        var path = Path.Combine(dir, desiredFileName);
        if (!File.Exists(path)) return null;

        try
        {
            var fi = new FileInfo(path);
            if (fi.Length == 0) return null;
            if (expectedSize > 0 && fi.Length != expectedSize) return null;
            return path;
        }
        catch { return null; }
    }

    /// <summary>Перемещает скачанный файл в кэш. Возвращает путь в кэше.</summary>
    public string Put(string fileId, string sourceFile, string desiredFileName)
    {
        var dir = Path.Combine(CacheDir, Sanitize(fileId));
        Directory.CreateDirectory(dir);
        var dest = Path.Combine(dir, desiredFileName);
        if (File.Exists(dest))
        {
            try { File.Delete(dest); } catch { }
        }
        File.Copy(sourceFile, dest, overwrite: true);
        return dest;
    }

    public long GetTotalSize()
    {
        if (!Directory.Exists(CacheDir)) return 0;
        long total = 0;
        try
        {
            foreach (var f in Directory.EnumerateFiles(CacheDir, "*", SearchOption.AllDirectories))
            {
                try { total += new FileInfo(f).Length; } catch { }
            }
        }
        catch { }
        return total;
    }

    public void Clear()
    {
        if (!Directory.Exists(CacheDir)) return;
        try
        {
            foreach (var sub in Directory.EnumerateDirectories(CacheDir))
            {
                try { Directory.Delete(sub, recursive: true); } catch { }
            }
            foreach (var f in Directory.EnumerateFiles(CacheDir))
            {
                try { File.Delete(f); } catch { }
            }
        }
        catch { }
    }

    private static string Sanitize(string s)
    {
        var sb = new StringBuilder(s.Length);
        foreach (var ch in s)
            sb.Append(char.IsLetterOrDigit(ch) || ch is '_' or '-' or '.' ? ch : '_');
        return sb.ToString();
    }
}

/// <summary>Утилита для подсчёта MD5/SHA1/SHA256 потоково.</summary>
public static class FileHashing
{
    public static string ComputeHex(string filePath, string algorithm)
    {
        algorithm = algorithm.ToUpperInvariant();
        using HashAlgorithm h = algorithm switch
        {
            "MD5" => MD5.Create(),
            "SHA1" => SHA1.Create(),
            "SHA256" => SHA256.Create(),
            _ => throw new NotSupportedException($"Unknown algorithm: {algorithm}")
        };
        using var fs = File.OpenRead(filePath);
        var bytes = h.ComputeHash(fs);
        var sb = new StringBuilder(bytes.Length * 2);
        foreach (var b in bytes) sb.Append(b.ToString("x2"));
        return sb.ToString();
    }
}
