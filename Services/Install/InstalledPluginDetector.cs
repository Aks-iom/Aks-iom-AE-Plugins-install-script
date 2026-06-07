using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using AEPluginInstaller.Models;

namespace AEPluginInstaller.Services.Install;

/// <summary>
/// Эвристически определяет, установлен ли плагин в данную AE — даже если он
/// поставлен вручную или сторонним инсталлером (то есть нет нашего манифеста).
///
/// Подход:
/// 1) Один раз сканируем папки AE (Plug-ins, Scripts, ScriptUI Panels, Presets,
///    общая MediaCore), собираем нормализованные имена всех файлов и подкаталогов.
/// 2) Для каждого плагина строим набор «кандидатов»: Name, Files[].FileName,
///    хвост Files[].TargetPath и Keywords из каталога/bundled JSON.
/// 3) Совпадение засчитывается, если:
///    • exact match по имени файла/папки или stem-у (≥3 символов);
///    • substring match (для кандидата ≥5 символов) — ловит "twixtor" в "twixtor8ae";
///    • prefix match (для кандидата 4 символов) — ловит "flow" в "Flow.jsxbin".
/// </summary>
public class InstalledPluginDetector
{
    private readonly HashSet<string> _fileNames;
    private readonly HashSet<string> _stems;       // имена без расширения
    private readonly HashSet<string> _dirNames;
    private readonly List<string> _allNames;       // плоский список всего что нашли — для substring
    private readonly Dictionary<string, List<string>> _bundledKeywords;

    private InstalledPluginDetector(
        HashSet<string> files,
        HashSet<string> stems,
        HashSet<string> dirs,
        List<string> allNames,
        Dictionary<string, List<string>> bundledKeywords)
    {
        _fileNames = files;
        _stems = stems;
        _dirNames = dirs;
        _allNames = allNames;
        _bundledKeywords = bundledKeywords;
    }

    public static InstalledPluginDetector Build(AfterEffectsInstallation ae)
    {
        var files = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var stems = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var dirs = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        // Общая для всех Adobe-приложений папка MediaCore (Red Giant, Sapphire OFX и т.п.).
        var pf = Environment.GetEnvironmentVariable("ProgramFiles") ?? @"C:\Program Files";
        var pf86 = Environment.GetEnvironmentVariable("ProgramFiles(x86)") ?? @"C:\Program Files (x86)";
        var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);

        var commonMediaCore = Path.Combine(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore");
        // CEP-расширения — system-wide и user-level (Flow, Prime Tool и подобные панели).
        var cepSystem = Path.Combine(pf86, "Common Files", "Adobe", "CEP", "extensions");
        var cepUser = Path.Combine(appData, "Adobe", "CEP", "extensions");
        // Скрипты на user-level (могут оказаться там, если bat-инсталлер положил туда).
        var userScripts = !string.IsNullOrEmpty(ae.Version)
            ? Path.Combine(appData, "Adobe", $"After Effects {ae.Version}", "Scripts")
            : "";

        // Корни, которые сканируем рекурсивно.
        var roots = new[]
        {
            ae.PluginsPath,
            ae.ScriptsPath,
            ae.ScriptUIPath,
            ae.PresetsPath,
            commonMediaCore,
            cepSystem,
            cepUser,
            userScripts
        };

        foreach (var root in roots.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            if (string.IsNullOrEmpty(root)) continue;
            CollectRecursive(root, files, stems, dirs, maxDepth: 4);
        }

        var allNames = new HashSet<string>(files, StringComparer.OrdinalIgnoreCase);
        allNames.UnionWith(dirs);
        allNames.UnionWith(stems);

        return new InstalledPluginDetector(
            files, stems, dirs, allNames.ToList(),
            LoadBundledKeywords());
    }

    /// <summary>
    /// Подгружает keywords из bundled JSON-каталогов (на случай, если у юзера
    /// уже сохранён старый конфиг без Keywords).
    /// </summary>
    private static Dictionary<string, List<string>> LoadBundledKeywords()
    {
        var dict = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
        var baseDir = AppContext.BaseDirectory;
        var paths = new[]
        {
            Path.Combine(baseDir, "Catalogs", "plugins.json"),
            Path.Combine(baseDir, "Catalogs", "extended_list.json")
        };
        foreach (var path in paths)
        {
            if (!File.Exists(path)) continue;
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(path));
                if (!doc.RootElement.TryGetProperty("plugins", out var arr)) continue;
                foreach (var p in arr.EnumerateArray())
                {
                    if (!p.TryGetProperty("name", out var nameEl)) continue;
                    var name = nameEl.GetString();
                    if (string.IsNullOrWhiteSpace(name)) continue;
                    if (!p.TryGetProperty("keywords", out var kw) || kw.ValueKind != JsonValueKind.Array) continue;
                    var list = new List<string>();
                    foreach (var k in kw.EnumerateArray())
                    {
                        if (k.ValueKind == JsonValueKind.String)
                        {
                            var s = k.GetString();
                            if (!string.IsNullOrWhiteSpace(s)) list.Add(s);
                        }
                    }
                    if (list.Count > 0) dict[name] = list;
                }
            }
            catch { }
        }
        return dict;
    }

    private static void CollectRecursive(string dir, HashSet<string> files,
        HashSet<string> stems, HashSet<string> dirs, int maxDepth)
    {
        if (maxDepth <= 0) return;
        if (!Directory.Exists(dir)) return;

        try
        {
            foreach (var f in Directory.EnumerateFiles(dir))
            {
                var name = Path.GetFileName(f);
                files.Add(Normalize(name));
                stems.Add(Normalize(Path.GetFileNameWithoutExtension(name)));
            }
        }
        catch { }

        try
        {
            foreach (var sub in Directory.EnumerateDirectories(dir))
            {
                var name = Path.GetFileName(sub);
                dirs.Add(Normalize(name));
                CollectRecursive(sub, files, stems, dirs, maxDepth - 1);
            }
        }
        catch { }
    }

    /// <summary>Возвращает true, если плагин похож на уже установленный.</summary>
    public bool IsInstalled(Plugin plugin)
    {
        foreach (var raw in BuildCandidates(plugin))
        {
            if (string.IsNullOrWhiteSpace(raw)) continue;
            var norm = Normalize(raw);
            if (norm.Length < 3) continue;

            // 1) точное совпадение имени файла или папки
            if (_fileNames.Contains(norm)) return true;
            if (_dirNames.Contains(norm)) return true;

            // 2) совпадение без расширения (например "Optical Flares" → "Optical Flares.aex")
            var stem = Normalize(Path.GetFileNameWithoutExtension(raw));
            if (stem.Length >= 3 && _stems.Contains(stem)) return true;

            // 3) substring — ловит "twixtor" внутри "twixtor8ae"
            if (norm.Length >= 5)
            {
                foreach (var name in _allNames)
                    if (name.Contains(norm, StringComparison.Ordinal)) return true;
            }
            // 4) префикс для 4-символьных кандидатов (например "flow" → "Flow.jsxbin")
            else if (norm.Length == 4)
            {
                foreach (var name in _allNames)
                    if (name.StartsWith(norm, StringComparison.Ordinal)) return true;
            }
        }
        return false;
    }

    /// <summary>Имена/подсказки, по которым стоит искать плагин на диске.</summary>
    private IEnumerable<string> BuildCandidates(Plugin plugin)
    {
        if (!string.IsNullOrWhiteSpace(plugin.Name))
            yield return plugin.Name;

        foreach (var kw in plugin.Keywords)
            if (!string.IsNullOrWhiteSpace(kw)) yield return kw;

        // Fallback на bundled keywords если у плагина их нет (старый сохранённый конфиг).
        if (plugin.Keywords.Count == 0
            && _bundledKeywords.TryGetValue(plugin.Name, out var fb))
        {
            foreach (var kw in fb) yield return kw;
        }

        foreach (var f in plugin.Files)
        {
            if (!string.IsNullOrWhiteSpace(f.FileName))
                yield return f.FileName;

            if (!string.IsNullOrWhiteSpace(f.TargetPath))
            {
                var leaf = SafeFileName(f.TargetPath);
                if (!string.IsNullOrEmpty(leaf)) yield return leaf;
            }
        }
    }

    private static string SafeFileName(string path)
    {
        try { return Path.GetFileName(path.Replace('/', '\\').TrimEnd('\\')) ?? ""; }
        catch { return ""; }
    }

    /// <summary>
    /// Нормализация имени: lower-case, удаляем пробелы/подчёркивания/дефисы/точки.
    /// Так совпадают "Optical_Flares" и "Optical Flares", "twixtor8ae" и "twixtor 8 ae".
    /// </summary>
    private static string Normalize(string s)
    {
        if (string.IsNullOrEmpty(s)) return "";
        var sb = new System.Text.StringBuilder(s.Length);
        foreach (var ch in s)
        {
            if (ch is ' ' or '_' or '-' or '.') continue;
            sb.Append(char.ToLowerInvariant(ch));
        }
        return sb.ToString();
    }
}
