using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace AEPluginInstaller.Services;

/// <summary>
/// Хранит список путей AE, которые пользователь скрыл из шапки.
/// Скрытие — по полному пути установки, а не по версии.
/// </summary>
public class AeBlacklistStore
{
    private readonly string _path;
    private HashSet<string> _paths = new(StringComparer.OrdinalIgnoreCase);

    public AeBlacklistStore()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "AEPluginInstaller");
        Directory.CreateDirectory(dir);
        _path = Path.Combine(dir, "ae_blacklist.json");
        Load();
    }

    private void Load()
    {
        if (!File.Exists(_path)) return;
        try
        {
            var list = JsonSerializer.Deserialize<List<string>>(File.ReadAllText(_path));
            if (list != null) _paths = new HashSet<string>(list, StringComparer.OrdinalIgnoreCase);
        }
        catch { }
    }

    private void Save()
    {
        try
        {
            File.WriteAllText(_path,
                JsonSerializer.Serialize(_paths.ToList(),
                    new JsonSerializerOptions { WriteIndented = true }));
        }
        catch { }
    }

    public bool IsBlacklisted(string path) => _paths.Contains(path);

    public void Add(string path)
    {
        if (_paths.Add(path)) Save();
    }

    public void Remove(string path)
    {
        if (_paths.Remove(path)) Save();
    }

    public IEnumerable<string> All() => _paths;
}
