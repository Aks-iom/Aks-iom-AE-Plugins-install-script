using System.Collections.Generic;
using System.IO;
using AEPluginInstaller.Models;

namespace AEPluginInstaller.Services.Install;

/// <summary>
/// Превращает плагин с <see cref="Plugin.Files"/> (наш формат custom_files
/// из extended_list.json) в JSON-манифест с install_steps.
/// </summary>
public static class CustomConverter
{
    /// <summary>Возвращает JSON-описание шагов для пакетного плагина.</summary>
    public static string BuildStepsJson(Plugin plugin)
    {
        var steps = new List<object>();

        foreach (var f in plugin.Files)
        {
            var src = "{SRC_DIR}/" + (string.IsNullOrEmpty(f.FileName)
                ? GuessFileName(f) : f.FileName);
            var target = NormalizeTarget(f.TargetPath);

            switch (f.Type)
            {
                case PluginType.Archive:
                    steps.Add(new {
                        type = "extract_zip",
                        source = src,
                        target = string.IsNullOrEmpty(target)
                            ? "{PLUGINS_DIR}/" + SafeFolder(plugin.Name)
                            : target
                    });
                    break;

                case PluginType.Installer:
                    steps.Add(new { type = "run_exe", path = src, wait = true });
                    break;

                case PluginType.RegFile:
                    steps.Add(new { type = "import_reg", path = src });
                    break;

                case PluginType.Plugin:
                case PluginType.Script:
                case PluginType.ScriptUI:
                case PluginType.Preset:
                case PluginType.Auto:
                default:
                    steps.Add(new {
                        type = "copy_file",
                        source = src,
                        target = string.IsNullOrEmpty(target) ? "{PLUGINS_DIR}" : target
                    });
                    break;
            }
        }

        return System.Text.Json.JsonSerializer.Serialize(steps);
    }

    private static string SafeFolder(string s)
    {
        var sb = new System.Text.StringBuilder(s.Length);
        foreach (var ch in s)
            sb.Append(char.IsLetterOrDigit(ch) || ch is '_' or '-' or '.' ? ch : '_');
        return sb.ToString();
    }

    private static string GuessFileName(PluginFile f) => f.Type switch
    {
        PluginType.Archive => "archive.zip",
        PluginType.Installer => "setup.exe",
        PluginType.RegFile => "keys.reg",
        _ => "file.bin"
    };

    /// <summary>
    /// Если в JSON стоит жёсткий путь типа
    /// <c>C:/Program Files/Adobe/Adobe After Effects 2023/Support Files/Plug-ins/X</c>,
    /// заменяем на <c>{PLUGINS_DIR}/X</c>. Аналогично для Scripts/ScriptUI Panels.
    /// </summary>
    private static string NormalizeTarget(string raw)
    {
        if (string.IsNullOrEmpty(raw)) return "";
        var norm = raw.Replace('\\', '/');
        var lower = norm.ToLowerInvariant();

        string? Replace(string anchor, string token)
        {
            var idx = lower.IndexOf(anchor);
            if (idx < 0) return null;
            var after = norm[(idx + anchor.Length)..].TrimStart('/');
            return string.IsNullOrEmpty(after) ? token : token + "/" + after;
        }

        return Replace("support files/scripts/scriptui panels", "{SCRIPTS_DIR}")
            ?? Replace("support files/scripts", "{AE_BASE}/Support Files/Scripts")
            ?? Replace("support files/plug-ins", "{PLUGINS_DIR}")
            ?? Replace("common files/adobe/cep/extensions", "{CEP_EXTENSIONS}")
            ?? norm;
    }
}
