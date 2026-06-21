using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace AEPluginInstaller.Services;

public class AfterEffectsInstallation
{
    /// <summary>«Год»-метка как в имени папки / папке Documents: "2024", "2025", "CC 2019".
    /// Используется для путей User Presets и подстановки {AE_VERSION}.</summary>
    public string Version { get; init; } = "";

    /// <summary>Корень установки: ...\Adobe After Effects 2024 (содержит подпапку Support Files).</summary>
    public string InstallPath { get; init; } = "";

    /// <summary>Двузначный код мажорной версии ("24", "25", "26") — то, чем
    /// «таблетки» версий в шапке сопоставляются с найденной установкой.</summary>
    public string MajorCode => AeVersionUtil.ToMajorCode(Version);

    public string PluginsPath => Path.Combine(InstallPath, "Support Files", "Plug-ins");
    public string ScriptsPath => Path.Combine(InstallPath, "Support Files", "Scripts");
    public string ScriptUIPath => Path.Combine(ScriptsPath, "ScriptUI Panels");

    public string PresetsPath
    {
        get
        {
            var docs = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
            return Path.Combine(docs, "Adobe", $"After Effects {Version}", "User Presets");
        }
    }

    public override string ToString() => $"After Effects {Version}";
}

/// <summary>Утилиты приведения версий AE к единому виду.</summary>
public static class AeVersionUtil
{
    private static readonly Regex YearRe = new(@"(?:19|20)(\d{2})", RegexOptions.Compiled);

    /// <summary>
    /// Приводит любую запись версии к двузначному коду мажора:
    ///   "2024" → "24", "2025 (Beta)" → "25", "CC 2019" → "19",
    ///   "24" → "24", "24.0.1" → "24". Если ничего распознать нельзя — вернёт вход без изменений.
    /// </summary>
    public static string ToMajorCode(string version)
    {
        if (string.IsNullOrWhiteSpace(version)) return "";
        version = version.Trim();

        // Полный год 20XX / 19XX → последние две цифры
        var ym = YearRe.Match(version);
        if (ym.Success) return ym.Groups[1].Value;

        // Уже двузначный код
        if (Regex.IsMatch(version, @"^\d{2}$")) return version;

        // major.minor (например "24.0.1") → "24"
        var dm = Regex.Match(version, @"^(\d{1,2})(?:\.\d+)*$");
        if (dm.Success) return dm.Groups[1].Value.PadLeft(2, '0');

        return version;
    }

    /// <summary>Извлекает «год»-метку ("2024") из произвольного суффикса имени папки,
    /// либо возвращает суффикс как есть, если года нет (легаси / Beta).</summary>
    public static string ToYearLabel(string rawSuffix)
    {
        if (string.IsNullOrWhiteSpace(rawSuffix)) return "";
        var m = Regex.Match(rawSuffix, @"(?:19|20)\d{2}");
        return m.Success ? m.Value : rawSuffix.Trim();
    }
}

public static class AfterEffectsLocator
{
    private static readonly Regex AeFolderRe =
        new(@"^Adobe After Effects (.+)$", RegexOptions.IgnoreCase | RegexOptions.Compiled);

    /// <summary>
    /// Ищет установки AE двумя способами:
    ///   1) реестр Windows (самый надёжный — ловит и нестандартные папки установки);
    ///   2) скан стандартных мест на всех фиксированных дисках.
    /// Результаты объединяются по <see cref="AfterEffectsInstallation.MajorCode"/>;
    /// приоритет у реестра.
    /// </summary>
    public static List<AfterEffectsInstallation> FindInstallations()
    {
        // ключ — MajorCode ("24"), чтобы одна и та же установка не задвоилась
        var found = new Dictionary<string, AfterEffectsInstallation>(StringComparer.OrdinalIgnoreCase);

        // 1) Реестр — первичный, самый точный источник
        foreach (var ae in ScanRegistry())
            AddIfBetter(found, ae);

        // 2) Скан дисков — дополняет реестр (например, портативная распаковка)
        foreach (var drive in GetSearchableDrives())
            foreach (var adobeDir in GetAdobeCandidates(drive))
                ScanAdobeDir(adobeDir, found);

        return found.Values
            .OrderByDescending(i => i.MajorCode, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static void AddIfBetter(Dictionary<string, AfterEffectsInstallation> dest,
                                    AfterEffectsInstallation ae)
    {
        if (string.IsNullOrEmpty(ae.MajorCode)) return;
        if (!dest.ContainsKey(ae.MajorCode)) dest[ae.MajorCode] = ae;
    }

    // ───────────────────────── реестр ─────────────────────────

    private static IEnumerable<AfterEffectsInstallation> ScanRegistry()
    {
        if (!OperatingSystem.IsWindows()) yield break;

        var results = new List<AfterEffectsInstallation>();

        // a) HKLM\SOFTWARE\Adobe\After Effects\<ver>  →  InstallPath (обычно ...\Support Files\)
        foreach (var hive in new[] { RegistryHive.LocalMachine, RegistryHive.CurrentUser })
        foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
        {
            TryReadAdobeKey(hive, view, results);
        }

        // b) Ключи деинсталляции: DisplayName "Adobe After Effects ..." → InstallLocation
        TryReadUninstallKeys(results);

        foreach (var r in results) yield return r;
    }

    private static void TryReadAdobeKey(RegistryHive hive, RegistryView view,
                                        List<AfterEffectsInstallation> dest)
    {
        try
        {
            using var baseKey = RegistryKey.OpenBaseKey(hive, view);
            using var ae = baseKey.OpenSubKey(@"SOFTWARE\Adobe\After Effects");
            if (ae == null) return;

            foreach (var verName in ae.GetSubKeyNames())
            {
                try
                {
                    using var verKey = ae.OpenSubKey(verName);
                    var installPath = verKey?.GetValue("InstallPath") as string;
                    if (string.IsNullOrWhiteSpace(installPath)) continue;

                    var root = NormalizeToInstallRoot(installPath);
                    if (root == null) continue;

                    dest.Add(new AfterEffectsInstallation
                    {
                        Version = VersionFromRootOrFallback(root, verName),
                        InstallPath = root
                    });
                }
                catch { /* пропускаем битый подключ */ }
            }
        }
        catch { /* нет прав / нет ветки */ }
    }

    private static void TryReadUninstallKeys(List<AfterEffectsInstallation> dest)
    {
        if (!OperatingSystem.IsWindows()) return;

        string[] roots =
        {
            @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            @"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
        };

        try
        {
            using var hklm = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64);
            foreach (var root in roots)
            {
                using var unin = hklm.OpenSubKey(root);
                if (unin == null) continue;

                foreach (var sub in unin.GetSubKeyNames())
                {
                    try
                    {
                        using var k = unin.OpenSubKey(sub);
                        var name = k?.GetValue("DisplayName") as string;
                        if (string.IsNullOrEmpty(name) ||
                            !name.StartsWith("Adobe After Effects", StringComparison.OrdinalIgnoreCase))
                            continue;

                        var loc = k?.GetValue("InstallLocation") as string;
                        var root2 = NormalizeToInstallRoot(loc);
                        if (root2 == null) continue;

                        dest.Add(new AfterEffectsInstallation
                        {
                            Version = VersionFromRootOrFallback(root2, name),
                            InstallPath = root2
                        });
                    }
                    catch { }
                }
            }
        }
        catch { }
    }

    /// <summary>
    /// Реестр часто хранит путь до «...\Support Files\» (или с финальным слэшем).
    /// Возвращаем корень установки (папку, содержащую Support Files), либо null,
    /// если по пути нет признаков AE.
    /// </summary>
    private static string? NormalizeToInstallRoot(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return null;
        var p = raw.Trim().TrimEnd('\\', '/');

        if (!SafeExists(p)) return null;

        // путь == корень (есть Support Files внутри)
        if (SafeExists(Path.Combine(p, "Support Files"))) return p;

        // путь == ...\Support Files  → поднимаемся на уровень
        if (string.Equals(Path.GetFileName(p), "Support Files", StringComparison.OrdinalIgnoreCase))
        {
            var parent = Path.GetDirectoryName(p);
            if (parent != null && SafeExists(Path.Combine(parent, "Support Files")))
                return parent;
        }

        return null;
    }

    private static string VersionFromRootOrFallback(string installRoot, string fallback)
    {
        var leaf = Path.GetFileName(installRoot);
        var m = AeFolderRe.Match(leaf);
        if (m.Success) return AeVersionUtil.ToYearLabel(m.Groups[1].Value);
        return AeVersionUtil.ToYearLabel(fallback);
    }

    // ───────────────────────── скан дисков ─────────────────────────

    private static IEnumerable<string> GetSearchableDrives()
    {
        DriveInfo[] drives;
        try { drives = DriveInfo.GetDrives(); }
        catch { yield break; }

        foreach (var d in drives)
        {
            bool ok;
            try
            {
                // Сканируем все локально подключённые диски (внутренние SSD/HDD,
                // внешние USB), но исключаем CD/DVD и сетевые шары — там почти
                // никогда нет AE и сканирование может зависнуть на медленной сети.
                ok = (d.DriveType == DriveType.Fixed
                      || d.DriveType == DriveType.Removable)
                     && d.IsReady;
            }
            catch { ok = false; }
            if (ok) yield return d.RootDirectory.FullName;
        }
    }

    private static IEnumerable<string> GetAdobeCandidates(string drive)
    {
        yield return Path.Combine(drive, "Program Files", "Adobe");
        yield return Path.Combine(drive, "Program Files (x86)", "Adobe");
        yield return Path.Combine(drive, "Adobe");

        // Реальные пути Program Files с текущей системы (учитывают перенаправления/локализацию).
        var pf = Environment.GetEnvironmentVariable("ProgramFiles");
        var pf86 = Environment.GetEnvironmentVariable("ProgramFiles(x86)");
        if (!string.IsNullOrEmpty(pf) &&
            string.Equals(Path.GetPathRoot(pf), drive, StringComparison.OrdinalIgnoreCase))
            yield return Path.Combine(pf, "Adobe");
        if (!string.IsNullOrEmpty(pf86) &&
            string.Equals(Path.GetPathRoot(pf86), drive, StringComparison.OrdinalIgnoreCase))
            yield return Path.Combine(pf86, "Adobe");
    }

    private static void ScanAdobeDir(string adobeDir, Dictionary<string, AfterEffectsInstallation> dest)
    {
        if (!SafeExists(adobeDir)) return;

        IEnumerable<string> children;
        try { children = Directory.EnumerateDirectories(adobeDir); }
        catch (UnauthorizedAccessException) { return; }
        catch (IOException) { return; }

        foreach (var dir in children)
        {
            var name = Path.GetFileName(dir);
            var m = AeFolderRe.Match(name);
            if (!m.Success) continue;

            var supportFiles = Path.Combine(dir, "Support Files");
            if (!SafeExists(supportFiles)) continue;

            var ae = new AfterEffectsInstallation
            {
                Version = AeVersionUtil.ToYearLabel(m.Groups[1].Value),
                InstallPath = dir
            };
            AddIfBetter(dest, ae);
        }
    }

    private static bool SafeExists(string path)
    {
        try { return Directory.Exists(path); }
        catch { return false; }
    }
}
