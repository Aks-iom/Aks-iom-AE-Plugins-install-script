using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;

namespace AEPluginInstaller.Services;

/// <summary>
/// Простой JSON-сторадж путей к AE, выбранных пользователем вручную через диалог «Обзор...».
/// Лежит в %AppData%\AEPluginInstaller\manual_ae_paths.json.
/// </summary>
public class ManualAePathStore
{
    private readonly string _path;
    private Dictionary<string, string> _data = new();

    public ManualAePathStore()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "AEPluginInstaller");
        Directory.CreateDirectory(dir);
        _path = Path.Combine(dir, "manual_ae_paths.json");
        Load();
    }

    private void Load()
    {
        if (!File.Exists(_path)) return;
        try
        {
            var json = File.ReadAllText(_path);
            _data = JsonSerializer.Deserialize<Dictionary<string, string>>(json)
                    ?? new Dictionary<string, string>();
        }
        catch { _data = new(); }
    }

    private void Save()
    {
        try
        {
            File.WriteAllText(_path, JsonSerializer.Serialize(_data,
                new JsonSerializerOptions { WriteIndented = true }));
        }
        catch { /* ignore */ }
    }

    public string? Get(string version) =>
        _data.TryGetValue(version, out var p) && Directory.Exists(p) ? p : null;

    public void Set(string version, string path)
    {
        _data[version] = path;
        Save();
    }

    public void Remove(string version)
    {
        if (_data.Remove(version)) Save();
    }

    /// <summary>Возвращает все валидные ручные пути как <see cref="AfterEffectsInstallation"/>.
    /// Метка версии достаётся из имени папки (".../Adobe After Effects 2024" → "2024"),
    /// чтобы корректно работали User Presets и сопоставление по MajorCode; при отсутствии
    /// года в имени — откат к "20" + сохранённый код.</summary>
    public IEnumerable<AfterEffectsInstallation> GetAll()
    {
        foreach (var (ver, path) in _data)
        {
            if (!Directory.Exists(path)) continue;

            var leaf = Path.GetFileName(path.TrimEnd('\\', '/')) ?? "";
            var m = System.Text.RegularExpressions.Regex.Match(leaf, @"(?:19|20)\d{2}");
            var label = m.Success ? m.Value : (ver.Length == 2 ? "20" + ver : ver);

            yield return new AfterEffectsInstallation { Version = label, InstallPath = path };
        }
    }
}
