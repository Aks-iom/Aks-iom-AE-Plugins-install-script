using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using AEPluginInstaller.Models;
using SharpCompress.Archives;
using SharpCompress.Common;

namespace AEPluginInstaller.Services;

public class PluginInstaller
{
    private readonly AfterEffectsInstallation _ae;
    public event Action<string>? Log;

    public PluginInstaller(AfterEffectsInstallation ae)
    {
        _ae = ae;
    }

    /// <summary>
    /// Устанавливает один скачанный файл, применяя override TargetPath если указан.
    /// </summary>
    public async Task<List<string>> InstallFileAsync(
        string downloadedFile,
        PluginType type,
        string targetPathOverride)
    {
        var installed = new List<string>();
        var ext = Path.GetExtension(downloadedFile).ToLowerInvariant();

        if (type == PluginType.Auto) type = InferFromExt(ext);

        if (type == PluginType.Installer || ext == ".exe")
        {
            Log?.Invoke($"  Запуск инсталлера: {Path.GetFileName(downloadedFile)}");
            Log?.Invoke($"  ⚠ Может потребоваться подтверждение UAC и ручные действия.");
            try
            {
                var psi = new ProcessStartInfo(downloadedFile) { UseShellExecute = true };
                var proc = Process.Start(psi);
                if (proc != null)
                {
                    await proc.WaitForExitAsync();
                    Log?.Invoke($"  Инсталлер завершён с кодом {proc.ExitCode}");
                }
                installed.Add(downloadedFile);
            }
            catch (Exception ex)
            {
                Log?.Invoke($"  ✖ Не удалось запустить инсталлер: {ex.Message}");
            }
            return installed;
        }

        if (type == PluginType.RegFile || ext == ".reg")
        {
            Log?.Invoke($"  Импорт REG: {Path.GetFileName(downloadedFile)}");
            try
            {
                var psi = new ProcessStartInfo("reg.exe", $"import \"{downloadedFile}\"")
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };
                var proc = Process.Start(psi)!;
                await proc.WaitForExitAsync();
                if (proc.ExitCode == 0)
                {
                    Log?.Invoke($"  ✔ Реестр обновлён");
                    installed.Add(downloadedFile);
                }
                else
                {
                    var err = await proc.StandardError.ReadToEndAsync();
                    Log?.Invoke($"  ✖ reg import код {proc.ExitCode}: {err.Trim()}");
                }
            }
            catch (Exception ex)
            {
                Log?.Invoke($"  ✖ Ошибка импорта REG: {ex.Message}");
            }
            return installed;
        }

        if (type == PluginType.Archive || IsArchive(ext))
        {
            installed.AddRange(await ExtractAndInstallArchiveAsync(downloadedFile, targetPathOverride));
            return installed;
        }

        var dest = !string.IsNullOrWhiteSpace(targetPathOverride)
            ? ResolvePath(targetPathOverride)
            : ResolveTargetFolderForFile(downloadedFile, type);

        var path = await CopyFileAsync(downloadedFile, dest);
        installed.Add(path);
        Log?.Invoke($"  → {path}");
        return installed;
    }

    private async Task<List<string>> ExtractAndInstallArchiveAsync(
        string archivePath, string targetPathOverride)
    {
        var installed = new List<string>();
        Log?.Invoke($"  Распаковка архива {Path.GetFileName(archivePath)}...");

        var tempDir = Path.Combine(Path.GetTempPath(), $"aeplugin_{Guid.NewGuid():N}");
        Directory.CreateDirectory(tempDir);

        try
        {
            await Task.Run(() =>
            {
                using var archive = ArchiveFactory.Open(archivePath);
                foreach (var entry in archive.Entries.Where(e => !e.IsDirectory))
                {
                    entry.WriteToDirectory(tempDir, new ExtractionOptions
                    {
                        ExtractFullPath = true,
                        Overwrite = true
                    });
                }
            });

            if (!string.IsNullOrWhiteSpace(targetPathOverride))
            {
                var dest = ResolvePath(targetPathOverride);
                Directory.CreateDirectory(dest);
                foreach (var f in Directory.EnumerateFiles(tempDir, "*", SearchOption.AllDirectories))
                {
                    var rel = Path.GetRelativePath(tempDir, f);
                    var outPath = Path.Combine(dest, rel);
                    Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
                    File.Copy(f, outPath, overwrite: true);
                    installed.Add(outPath);
                }
                Log?.Invoke($"  → Распаковано {installed.Count} файлов в {dest}");
                return installed;
            }

            foreach (var file in Directory.EnumerateFiles(tempDir, "*", SearchOption.AllDirectories))
            {
                var ext = Path.GetExtension(file).ToLowerInvariant();
                if (!IsKnownAeFile(ext)) continue;

                var target = ResolveTargetFolderForFile(file, PluginType.Auto);
                var rel = Path.GetRelativePath(tempDir, file);
                var relDir = Path.GetDirectoryName(rel);

                string destFolder = target;
                if (!string.IsNullOrEmpty(relDir))
                {
                    var parts = relDir.Split(Path.DirectorySeparatorChar,
                                             StringSplitOptions.RemoveEmptyEntries);
                    if (parts.Length > 1)
                        destFolder = Path.Combine(target,
                            string.Join(Path.DirectorySeparatorChar, parts.Skip(1)));
                }

                var path = await CopyFileAsync(file, destFolder);
                installed.Add(path);
                Log?.Invoke($"  → {path}");
            }
        }
        finally
        {
            try { Directory.Delete(tempDir, true); } catch { /* ignore */ }
        }

        return installed;
    }

    private string ResolveTargetFolderForFile(string file, PluginType hint)
    {
        var ext = Path.GetExtension(file).ToLowerInvariant();
        var name = Path.GetFileName(file).ToLowerInvariant();

        switch (hint)
        {
            case PluginType.Plugin:   return _ae.PluginsPath;
            case PluginType.Script:   return _ae.ScriptsPath;
            case PluginType.ScriptUI: return _ae.ScriptUIPath;
            case PluginType.Preset:   return _ae.PresetsPath;
        }

        return ext switch
        {
            ".aex" or ".plugin" or ".dll" => _ae.PluginsPath,
            ".ffx" => _ae.PresetsPath,
            ".jsx" or ".jsxbin" =>
                (name.Contains("panel") || name.Contains("scriptui"))
                    ? _ae.ScriptUIPath
                    : _ae.ScriptsPath,
            _ => _ae.PluginsPath
        };
    }

    private async Task<string> CopyFileAsync(string source, string destFolder)
    {
        Directory.CreateDirectory(destFolder);
        var dest = Path.Combine(destFolder, Path.GetFileName(source));

        if (File.Exists(dest))
        {
            var bak = dest + ".bak";
            if (File.Exists(bak)) File.Delete(bak);
            File.Move(dest, bak);
        }

        await using var src = File.OpenRead(source);
        await using var dst = File.Create(dest);
        await src.CopyToAsync(dst);
        return dest;
    }

    private static bool IsArchive(string ext) =>
        ext is ".zip" or ".rar" or ".7z" or ".tar" or ".gz";

    private static bool IsKnownAeFile(string ext) =>
        ext is ".aex" or ".plugin" or ".dll"
            or ".jsx" or ".jsxbin"
            or ".ffx"
            or ".aep";

    private static PluginType InferFromExt(string ext) => ext switch
    {
        ".aex" or ".plugin" or ".dll" => PluginType.Plugin,
        ".jsx" or ".jsxbin" => PluginType.Script,
        ".ffx" => PluginType.Preset,
        ".reg" => PluginType.RegFile,
        ".exe" => PluginType.Installer,
        ".zip" or ".rar" or ".7z" => PluginType.Archive,
        _ => PluginType.Auto
    };

    public string ResolvePath(string raw)
    {
        return raw
            .Replace("{plugins}", _ae.PluginsPath, StringComparison.OrdinalIgnoreCase)
            .Replace("{scripts}", _ae.ScriptsPath, StringComparison.OrdinalIgnoreCase)
            .Replace("{scriptui}", _ae.ScriptUIPath, StringComparison.OrdinalIgnoreCase)
            .Replace("{presets}", _ae.PresetsPath, StringComparison.OrdinalIgnoreCase)
            .Replace("{ae}", _ae.InstallPath, StringComparison.OrdinalIgnoreCase);
    }
}
