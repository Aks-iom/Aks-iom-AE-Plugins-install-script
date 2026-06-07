using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using AEPluginInstaller.Models;

namespace AEPluginInstaller.Services;

public class ConfigService
{
    private readonly string _configsDir;
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = true,
        Converters = { new System.Text.Json.Serialization.JsonStringEnumConverter() }
    };

    public ConfigService()
    {
        _configsDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "AEPluginInstaller", "configs");
        Directory.CreateDirectory(_configsDir);
    }

    public string ConfigsDirectory => _configsDir;

    public List<PluginConfig> LoadAll()
    {
        var list = new List<PluginConfig>();
        foreach (var file in Directory.EnumerateFiles(_configsDir, "*.json"))
        {
            try
            {
                var json = File.ReadAllText(file);
                var cfg = JsonSerializer.Deserialize<PluginConfig>(json, JsonOpts);
                if (cfg != null) list.Add(cfg);
            }
            catch { /* битый файл — пропускаем */ }
        }
        return list.OrderBy(c => c.Name).ToList();
    }

    public void Save(PluginConfig cfg)
    {
        var safe = SanitizeName(cfg.Name);
        var path = Path.Combine(_configsDir, safe + ".json");
        File.WriteAllText(path, JsonSerializer.Serialize(cfg, JsonOpts));
    }

    public void Delete(PluginConfig cfg)
    {
        var path = Path.Combine(_configsDir, SanitizeName(cfg.Name) + ".json");
        if (File.Exists(path)) File.Delete(path);
    }

    public void Rename(PluginConfig cfg, string oldName)
    {
        var oldPath = Path.Combine(_configsDir, SanitizeName(oldName) + ".json");
        if (File.Exists(oldPath)) File.Delete(oldPath);
        Save(cfg);
    }

    private static string SanitizeName(string n)
    {
        foreach (var c in Path.GetInvalidFileNameChars())
            n = n.Replace(c, '_');
        return n;
    }
}
