using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;

namespace AEPluginInstaller.Services.Install;

/// <summary>
/// Контекст одной установки. Все шаги получают его и используют
/// <see cref="Expand"/> для подстановки путей вида <c>{PLUGINS_DIR}</c>.
/// </summary>
public class InstallContext
{
    public string PluginName { get; init; } = "";
    public string AeVersion { get; init; } = "";
    public string SrcDir { get; init; } = "";
    public Dictionary<string, string> Paths { get; init; } = new();
    public string? CustomPath { get; init; }
    public Dictionary<string, object> Options { get; init; } = new();

    /// <summary>Логгер — UI подключает свой; по умолчанию no-op.</summary>
    public Action<string> Log { get; init; } = _ => { };

    /// <summary>
    /// Ссылка на текущую транзакцию — шаги типа CopyDir(replace) регистрируют
    /// в неё бэкапы. Выставляется движком перед циклом шагов.
    /// </summary>
    public InstallTransaction? Transaction { get; set; }

    private static readonly Regex AeVersionRe =
        new(@"(?i)(After Effects\s*)20\d{2}", RegexOptions.Compiled);

    private static readonly Regex VarRe =
        new(@"\{([A-Z_][A-Z0-9_]*)\}", RegexOptions.Compiled);

    /// <summary>Подставляет {VAR} из Paths/SrcDir/CustomPath и заменяет «After Effects 20XX».</summary>
    public string Expand(string? template)
    {
        if (string.IsNullOrEmpty(template)) return "";

        var locals = new Dictionary<string, string>(Paths, StringComparer.OrdinalIgnoreCase)
        {
            ["SRC_DIR"] = SrcDir ?? "",
            ["CUSTOM_PATH"] = CustomPath ?? ""
        };

        var result = VarRe.Replace(template, m =>
            locals.TryGetValue(m.Groups[1].Value, out var v) ? v : m.Value);

        if (!string.IsNullOrEmpty(AeVersion) && AeVersion != "None")
            result = AeVersionRe.Replace(result, $"${{1}}{AeVersion}");

        return result;
    }

    public bool GetBoolOption(string dotted)
    {
        if (string.IsNullOrEmpty(dotted)) return false;
        var parts = dotted.Split('.');
        if (parts[0] == "options") parts = parts[1..];
        object? cur = Options;
        foreach (var p in parts)
        {
            if (cur is IDictionary<string, object> d && d.TryGetValue(p, out var next))
                cur = next;
            else return false;
        }
        return cur switch
        {
            bool b => b,
            string s => bool.TryParse(s, out var bv) && bv,
            int i => i != 0,
            _ => cur != null
        };
    }
}

/// <summary>Строит стандартный набор путей для AE.</summary>
public static class DefaultPaths
{
    /// <param name="aeVersion">"2024", "23" и т.п.</param>
    /// <param name="customInstallPath">
    /// Корень установки AE (содержит подпапку Support Files). Если задан — используется он,
    /// иначе путь собирается из %ProgramFiles%\Adobe\Adobe After Effects {aeVersion}.
    /// </param>
    public static Dictionary<string, string> Build(
        string aeVersion,
        string customInstallPath = "")
    {
        var pf = Environment.GetEnvironmentVariable("ProgramFiles") ?? @"C:\Program Files";
        var pf86 = Environment.GetEnvironmentVariable("ProgramFiles(x86)") ?? @"C:\Program Files (x86)";
        var pd = Environment.GetEnvironmentVariable("ProgramData") ?? @"C:\ProgramData";

        var baseDir = !string.IsNullOrEmpty(customInstallPath)
            ? customInstallPath
            : Path.Combine(pf, "Adobe", $"Adobe After Effects {aeVersion}");

        var pluginsDir = Path.Combine(baseDir, "Support Files", "Plug-ins");
        var scriptsDir = Path.Combine(baseDir, "Support Files", "Scripts", "ScriptUI Panels");
        var presetsDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
            "Adobe", $"After Effects {aeVersion}", "User Presets");

        return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["PF"] = pf,
            ["PF86"] = pf86,
            ["PROGRAMDATA"] = pd,
            ["AE_VERSION"] = aeVersion,
            ["AE_BASE"] = baseDir,
            ["PLUGINS_DIR"] = pluginsDir,
            ["SCRIPTS_DIR"] = scriptsDir,
            ["PRESETS_DIR"] = presetsDir,
            ["COMMON_PLUGINS"] = Path.Combine(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore"),
            ["CEP_EXTENSIONS"] = Path.Combine(pf86, "Common Files", "Adobe", "CEP", "extensions"),
            ["USER_DOCS"] = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments)
        };
    }
}
