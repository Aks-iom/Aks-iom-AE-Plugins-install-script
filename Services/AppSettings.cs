using System;
using System.IO;
using System.Text.Json;

namespace AEPluginInstaller.Services;

public class AppSettingsData
{
    public string Language { get; set; } = ""; // "", "ru", "en"
    public long CacheSizeLimitBytes { get; set; } = 0; // 0 = бессрочно
}

public class AppSettings
{
    private readonly string _path;
    public AppSettingsData Data { get; private set; } = new();

    public AppSettings()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "AEPluginInstaller");
        Directory.CreateDirectory(dir);
        _path = Path.Combine(dir, "settings.json");
        Load();
    }

    private void Load()
    {
        if (!File.Exists(_path)) return;
        try
        {
            Data = JsonSerializer.Deserialize<AppSettingsData>(File.ReadAllText(_path))
                   ?? new AppSettingsData();
        }
        catch { Data = new(); }
    }

    public void Save()
    {
        try
        {
            File.WriteAllText(_path,
                JsonSerializer.Serialize(Data, new JsonSerializerOptions { WriteIndented = true }));
        }
        catch { }
    }
}
