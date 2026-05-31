using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using AEPluginInstaller.Models;

namespace AEPluginInstaller.Services;

/// <summary>
/// Парсит JSON-каталоги плагинов (plugins.json и extended_list.json),
/// которые поставляются вместе с приложением, и превращает их в PluginConfig.
/// </summary>
public static class CatalogImporter
{
    /// <summary>
    /// Парсит plugins.json (формат с gdrive_id и bat_path).
    /// Это набор архивов/инсталлеров — все они помечаются как Archive
    /// и при установке распаковываются, а раскладка определяется по содержимому.
    /// </summary>
    public static PluginConfig? ImportBasicCatalog(string jsonPath, string configName, string description)
    {
        if (!File.Exists(jsonPath)) return null;

        using var doc = JsonDocument.Parse(File.ReadAllText(jsonPath));
        if (!doc.RootElement.TryGetProperty("plugins", out var arr)) return null;

        var cfg = new PluginConfig { Name = configName, Description = description };

        foreach (var p in arr.EnumerateArray())
        {
            var name = p.GetProperty("name").GetString() ?? "?";
            var id = p.GetProperty("gdrive_id").GetString() ?? "";
            var size = p.TryGetProperty("size", out var s) ? s.GetString() ?? "" : "";
            var ver = p.TryGetProperty("version", out var v) ? v.GetString() ?? "" : "";
            var batPath = p.TryGetProperty("bat_path", out var bp) ? bp.GetString() ?? "" : "";

            // Пропускаем placeholder-ы (не настоящие id)
            if (string.IsNullOrEmpty(id) || id.StartsWith("PLACEHOLDER", StringComparison.OrdinalIgnoreCase))
                continue;

            // Если bat_path указывает на .exe/.bat — это инсталлятор: архив надо
            // распаковать и ЗАПУСТИТЬ указанный файл (а не просто разложить по Plug-ins).
            var runAfter = "";
            var ext = System.IO.Path.GetExtension(batPath).ToLowerInvariant();
            if (ext is ".exe" or ".bat" or ".cmd")
                runAfter = batPath;

            cfg.Plugins.Add(new Plugin
            {
                Name = name,
                Version = ver,
                Size = size,
                GoogleDriveUrl = id,
                Type = PluginType.Archive,
                RunAfterExtract = runAfter,
                Description = $"{ver}  •  {size}",
                Hash = p.TryGetProperty("md5", out var md5) && md5.ValueKind == JsonValueKind.String
                    ? md5.GetString() ?? "" : "",
                Keywords = ReadKeywords(p)
            });
        }

        return cfg;
    }

    private static List<string> ReadKeywords(JsonElement p)
    {
        var list = new List<string>();
        if (!p.TryGetProperty("keywords", out var kw) || kw.ValueKind != JsonValueKind.Array)
            return list;
        foreach (var k in kw.EnumerateArray())
        {
            if (k.ValueKind == JsonValueKind.String)
            {
                var s = k.GetString();
                if (!string.IsNullOrWhiteSpace(s)) list.Add(s);
            }
        }
        return list;
    }

    /// <summary>
    /// Парсит extended_list.json (расширенный формат с custom_files и target_path).
    /// Каждый плагин может иметь несколько файлов разных типов.
    /// </summary>
    public static PluginConfig? ImportExtendedCatalog(string jsonPath, string configName, string description)
    {
        if (!File.Exists(jsonPath)) return null;

        using var doc = JsonDocument.Parse(File.ReadAllText(jsonPath));
        if (!doc.RootElement.TryGetProperty("plugins", out var arr)) return null;

        var cfg = new PluginConfig { Name = configName, Description = description };

        foreach (var p in arr.EnumerateArray())
        {
            var name = p.GetProperty("name").GetString() ?? "?";
            var size = p.TryGetProperty("size", out var s) ? s.GetString() ?? "" : "";
            var ver = p.TryGetProperty("version", out var v) ? v.GetString() ?? "" : "";
            var warning = p.TryGetProperty("warning_text", out var w) ? w.GetString() ?? "" : "";

            var plugin = new Plugin
            {
                Name = name,
                Version = ver,
                Size = size,
                Warning = warning,
                Description = $"{ver}  •  {size}" + (string.IsNullOrEmpty(warning) ? "" : "  ⚠ " + warning),
                Keywords = ReadKeywords(p)
            };

            if (!p.TryGetProperty("custom_files", out var customFiles))
                continue;

            foreach (var fileProp in customFiles.EnumerateObject())
            {
                var typeKey = fileProp.Name; // "zip" / "file" / "exe" / "reg"
                var fileObj = fileProp.Value;

                var gid = fileObj.TryGetProperty("gdrive_id", out var idEl) ? idEl.GetString() ?? "" : "";
                if (string.IsNullOrEmpty(gid)) continue;

                var fname = fileObj.TryGetProperty("filename", out var fnEl) ? fnEl.GetString() ?? "" : "";
                var target = fileObj.TryGetProperty("target_path", out var tpEl) ? tpEl.GetString() ?? "" : "";

                // Нормализуем путь — заменяем жёстко вписанный «After Effects 2023» на подстановку
                target = NormalizeTargetPath(target, typeKey, fname);

                var typeEnum = typeKey switch
                {
                    "zip" => PluginType.Archive,
                    "exe" => PluginType.Installer,
                    "reg" => PluginType.RegFile,
                    "file" => InferFileType(fname),
                    _ => PluginType.Auto
                };

                plugin.Files.Add(new PluginFile
                {
                    GoogleDriveUrl = gid,
                    FileName = fname,
                    Type = typeEnum,
                    TargetPath = target
                });
            }

            if (plugin.Files.Count > 0)
                cfg.Plugins.Add(plugin);
        }

        return cfg;
    }

    /// <summary>
    /// Принимает «жёсткий» путь типа
    /// C:/Program Files/Adobe/Adobe After Effects 2023/Support Files/Scripts/ScriptUI Panels
    /// и подменяет версию AE на подстановку {plugins}/{scripts}/{scriptui}, если возможно.
    /// </summary>
    private static string NormalizeTargetPath(string raw, string typeKey, string fileName)
    {
        if (string.IsNullOrEmpty(raw)) return raw;

        var lower = raw.Replace('\\', '/').ToLowerInvariant();

        if (lower.Contains("/scriptui panels"))
            return ExtractSuffixAfterAe(raw, "Support Files/Scripts/ScriptUI Panels", "{scriptui}");
        if (lower.Contains("/scripts/") || lower.EndsWith("/scripts"))
            return ExtractSuffixAfterAe(raw, "Support Files/Scripts", "{scripts}");
        if (lower.Contains("/plug-ins"))
            return ExtractSuffixAfterAe(raw, "Support Files/Plug-ins", "{plugins}");

        // путь не относится к AE (например, CEP extensions, или корень C:/) — оставляем как есть,
        // только нормализуем слэши
        return raw.Replace('/', Path.DirectorySeparatorChar);
    }

    private static string ExtractSuffixAfterAe(string raw, string anchor, string token)
    {
        var norm = raw.Replace('\\', '/');
        var idx = norm.IndexOf(anchor, StringComparison.OrdinalIgnoreCase);
        if (idx < 0) return raw.Replace('/', Path.DirectorySeparatorChar);
        var afterAnchor = norm[(idx + anchor.Length)..].TrimStart('/');
        return string.IsNullOrEmpty(afterAnchor)
            ? token
            : Path.Combine(token, afterAnchor.Replace('/', Path.DirectorySeparatorChar));
    }

    private static PluginType InferFileType(string fileName)
    {
        var ext = Path.GetExtension(fileName).ToLowerInvariant();
        return ext switch
        {
            ".aex" or ".plugin" or ".dll" => PluginType.Plugin,
            ".jsx" or ".jsxbin" => PluginType.Script,
            ".ffx" => PluginType.Preset,
            ".reg" => PluginType.RegFile,
            ".exe" => PluginType.Installer,
            ".zip" or ".rar" or ".7z" => PluginType.Archive,
            _ => PluginType.Auto
        };
    }
}
