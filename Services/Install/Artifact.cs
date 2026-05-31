using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Win32;

namespace AEPluginInstaller.Services.Install;

/// <summary>Тип артефакта — что именно было создано на диске/в реестре.</summary>
public enum ArtifactType
{
    File,
    Dir,
    RegValue,
    RegKey,
    /// <summary>Запущенный .exe-инсталлер — откат невозможен, только предупреждение.</summary>
    ExeInstall
}

/// <summary>
/// Один созданный во время установки объект. Хранится в манифесте,
/// чтобы при удалении плагина или откате транзакции точно знать, что снести.
/// </summary>
public class Artifact
{
    public ArtifactType Type { get; set; }
    public string Path { get; set; } = "";
    public Dictionary<string, object> Extra { get; set; } = new();

    public static Artifact File(string path) => new() { Type = ArtifactType.File, Path = path };
    public static Artifact Dir(string path) => new() { Type = ArtifactType.Dir, Path = path };
    public static Artifact RegValue(string fullPath, bool wow64 = false) => new()
    {
        Type = ArtifactType.RegValue, Path = fullPath, Extra = { ["wow64"] = wow64 }
    };
    public static Artifact ExeInstall(string exePath) => new() { Type = ArtifactType.ExeInstall, Path = exePath };

    /// <summary>Как <see cref="ExeInstall(string)"/>, но сохраняет аргументы запуска
    /// в Extra["args"] — паритет с Python (<c>extra={"args": args}</c>).</summary>
    public static Artifact ExeInstall(string exePath, IEnumerable<string> args) => new()
    {
        Type = ArtifactType.ExeInstall,
        Path = exePath,
        Extra = { ["args"] = args.ToList() }
    };
}

/// <summary>Результат выполнения одного шага.</summary>
public class StepResult
{
    public bool Success { get; init; }
    public List<Artifact> Artifacts { get; init; } = new();
    public string? Error { get; init; }

    public static StepResult Ok(List<Artifact>? artifacts = null) =>
        new() { Success = true, Artifacts = artifacts ?? new() };

    public static StepResult Fail(string error, List<Artifact>? artifacts = null) =>
        new() { Success = false, Error = error, Artifacts = artifacts ?? new() };
}

/// <summary>
/// Удаление одного артефакта. Безопасно — никогда не бросает исключений
/// (если не задано ignoreErrors=false).
/// </summary>
public static class ArtifactRemover
{
    public static bool Remove(Artifact a, bool ignoreErrors = true)
    {
        try
        {
            switch (a.Type)
            {
                case ArtifactType.File:
                    if (System.IO.File.Exists(a.Path))
                    {
                        // Снимаем атрибут readonly, если выставлен
                        try { System.IO.File.SetAttributes(a.Path, FileAttributes.Normal); } catch { }
                        System.IO.File.Delete(a.Path);
                    }
                    return true;

                case ArtifactType.Dir:
                    if (Directory.Exists(a.Path))
                        Directory.Delete(a.Path, recursive: true);
                    return true;

                case ArtifactType.RegValue:
                    return RemoveRegValue(a);

                case ArtifactType.RegKey:
                    return RemoveRegKeyRecursive(a);

                case ArtifactType.ExeInstall:
                    // .exe-инсталлеры не откатываются — это задача «Программы и компоненты»
                    return true;
            }
        }
        catch
        {
            if (!ignoreErrors) throw;
            return false;
        }
        return false;
    }

    private static (RegistryKey? hive, string subkey, string valueName, bool wow64) ParseRegValuePath(Artifact a)
    {
        // Формат: "HKLM\Software\X\Y\ValueName"
        var parts = a.Path.Split('\\');
        if (parts.Length < 2) return (null, "", "", false);
        var hiveStr = parts[0];
        var name = parts[^1];
        var sub = string.Join('\\', parts[1..^1]);
        var hive = ResolveHive(hiveStr);
        var wow64 = a.Extra.TryGetValue("wow64", out var w) && Convert.ToBoolean(w);
        return (hive, sub, name, wow64);
    }

    private static RegistryKey? ResolveHive(string hive) => hive.ToUpperInvariant() switch
    {
        "HKLM" or "HKEY_LOCAL_MACHINE" => Registry.LocalMachine,
        "HKCU" or "HKEY_CURRENT_USER" => Registry.CurrentUser,
        _ => null
    };

    private static bool RemoveRegValue(Artifact a)
    {
        if (!OperatingSystem.IsWindows()) return true;
        var (hive, sub, name, wow64) = ParseRegValuePath(a);
        if (hive == null) return false;

        var view = wow64 ? RegistryView.Registry64 : RegistryView.Default;
        using var baseKey = RegistryKey.OpenBaseKey(
            hive == Registry.LocalMachine ? RegistryHive.LocalMachine : RegistryHive.CurrentUser, view);
        using var key = baseKey.OpenSubKey(sub, writable: true);
        if (key == null) return true; // уже нет
        try { key.DeleteValue(name, throwOnMissingValue: false); } catch { }
        return true;
    }

    private static bool RemoveRegKeyRecursive(Artifact a)
    {
        if (!OperatingSystem.IsWindows()) return true;
        // Формат: "HKLM\Software\X\Sub"
        var parts = a.Path.Split('\\');
        if (parts.Length < 2) return false;
        var hive = ResolveHive(parts[0]);
        if (hive == null) return false;
        var sub = string.Join('\\', parts[1..]);
        var wow64 = a.Extra.TryGetValue("wow64", out var w) && Convert.ToBoolean(w);
        var view = wow64 ? RegistryView.Registry64 : RegistryView.Default;
        using var baseKey = RegistryKey.OpenBaseKey(
            hive == Registry.LocalMachine ? RegistryHive.LocalMachine : RegistryHive.CurrentUser, view);
        try { baseKey.DeleteSubKeyTree(sub, throwOnMissingSubKey: false); } catch { return false; }
        return true;
    }
}

/// <summary>Манифест установленного плагина — JSON в %AppData%\AEPluginInstaller\installed.</summary>
public class InstalledManifestData
{
    [JsonPropertyName("plugin")] public string Plugin { get; set; } = "";
    [JsonPropertyName("ae_version")] public string AeVersion { get; set; } = "";
    [JsonPropertyName("installed_at")] public string InstalledAt { get; set; } = "";
    [JsonPropertyName("version")] public string Version { get; set; } = "";
    [JsonPropertyName("source")] public string Source { get; set; } = "managed";
    [JsonPropertyName("artifacts")] public List<Artifact> Artifacts { get; set; } = new();
}

/// <summary>Чтение/запись/удаление файла манифеста.</summary>
public static class InstalledManifest
{
    public const string SourceManaged = "managed";
    public const string SourceLegacy = "legacy";

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter() }
    };

    private static string SafeName(string s)
    {
        var sb = new System.Text.StringBuilder(s.Length);
        foreach (var ch in s)
            sb.Append(char.IsLetterOrDigit(ch) || ch is '.' or '_' or '-' ? ch : '_');
        return sb.ToString();
    }

    public static string GetPath(string installedDir, string plugin, string aeVersion)
        => System.IO.Path.Combine(installedDir, $"{SafeName(plugin)}__{SafeName(aeVersion)}.json");

    public static void Write(string installedDir, string plugin, string aeVersion,
        string pluginVersion, List<Artifact> artifacts, string source = SourceManaged)
    {
        Directory.CreateDirectory(installedDir);
        var data = new InstalledManifestData
        {
            Plugin = plugin,
            AeVersion = aeVersion,
            InstalledAt = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
            Version = pluginVersion,
            Source = source,
            Artifacts = artifacts
        };
        var path = GetPath(installedDir, plugin, aeVersion);
        var tmp = path + ".tmp";
        System.IO.File.WriteAllText(tmp, JsonSerializer.Serialize(data, JsonOpts));
        // Атомарная замена
        if (System.IO.File.Exists(path)) System.IO.File.Replace(tmp, path, null);
        else System.IO.File.Move(tmp, path);
    }

    public static InstalledManifestData? Read(string installedDir, string plugin, string aeVersion)
    {
        var path = GetPath(installedDir, plugin, aeVersion);
        if (!System.IO.File.Exists(path)) return null;
        try
        {
            return JsonSerializer.Deserialize<InstalledManifestData>(
                System.IO.File.ReadAllText(path), JsonOpts);
        }
        catch { return null; }
    }

    public static bool Delete(string installedDir, string plugin, string aeVersion)
    {
        var path = GetPath(installedDir, plugin, aeVersion);
        if (!System.IO.File.Exists(path)) return true;
        try { System.IO.File.Delete(path); return true; } catch { return false; }
    }

    /// <summary>Проверяет, что все артефакты ещё существуют.</summary>
    public static bool ArtifactsPresent(InstalledManifestData m)
    {
        foreach (var a in m.Artifacts)
        {
            switch (a.Type)
            {
                case ArtifactType.File:
                    if (!System.IO.File.Exists(a.Path)) return false;
                    break;
                case ArtifactType.Dir:
                    if (!Directory.Exists(a.Path)) return false;
                    if (a.Extra.TryGetValue("non_empty", out var n) && Convert.ToBoolean(n))
                    {
                        try
                        {
                            if (!Directory.EnumerateFileSystemEntries(a.Path).Any())
                                return false;
                        }
                        catch { return false; }
                    }
                    break;
                case ArtifactType.RegValue:
                    if (!OperatingSystem.IsWindows()) continue;
                    if (!RegValueExists(a)) return false;
                    break;
            }
        }
        return true;
    }

    private static bool RegValueExists(Artifact a)
    {
        if (!OperatingSystem.IsWindows()) return true;
        var parts = a.Path.Split('\\');
        if (parts.Length < 2) return false;
        var hiveStr = parts[0].ToUpperInvariant();
        var name = parts[^1];
        var sub = string.Join('\\', parts[1..^1]);

        var hive = hiveStr switch
        {
            "HKLM" or "HKEY_LOCAL_MACHINE" => RegistryHive.LocalMachine,
            "HKCU" or "HKEY_CURRENT_USER" => RegistryHive.CurrentUser,
            _ => (RegistryHive?)null
        };
        if (hive == null) return false;
        var wow64 = a.Extra.TryGetValue("wow64", out var w) && Convert.ToBoolean(w);
        var view = wow64 ? RegistryView.Registry64 : RegistryView.Default;
        try
        {
            using var baseKey = RegistryKey.OpenBaseKey(hive.Value, view);
            using var k = baseKey.OpenSubKey(sub);
            if (k == null) return false;
            return k.GetValue(name) != null;
        }
        catch { return false; }
    }
}
