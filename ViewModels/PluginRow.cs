using System.ComponentModel;
using System.Runtime.CompilerServices;
using AEPluginInstaller.Models;

namespace AEPluginInstaller.ViewModels;

public class PluginRow : INotifyPropertyChanged
{
    private readonly Plugin _plugin;

    public PluginRow(Plugin plugin)
    {
        _plugin = plugin;
        IsSelected = false;
    }

    public Plugin Model => _plugin;

    public string Name => _plugin.Name;
    public string Version => _plugin.Version;
    public string Size => _plugin.Size;

    public string VersionDisplay => string.IsNullOrEmpty(_plugin.Version)
        ? "" : $"v{_plugin.Version}";
    public bool HasVersion => !string.IsNullOrEmpty(_plugin.Version);

    public string Subtitle
    {
        get
        {
            var url = _plugin.GoogleDriveUrl;
            if (string.IsNullOrEmpty(url) && _plugin.Files.Count > 0)
                return $"{_plugin.Files.Count} файл(ов)" +
                    (string.IsNullOrEmpty(_plugin.Warning) ? "" : $"  ⚠ {_plugin.Warning}");
            if (!string.IsNullOrEmpty(_plugin.Warning))
                return "⚠ " + _plugin.Warning;
            if (!string.IsNullOrEmpty(_plugin.Description) && _plugin.Description != $"{_plugin.Version}  •  {_plugin.Size}")
                return _plugin.Description;
            return "";
        }
    }
    public bool HasSubtitle => !string.IsNullOrEmpty(Subtitle);

    private bool _isSelected;
    public bool IsSelected
    {
        get => _isSelected;
        set { _isSelected = value; Notify(); }
    }

    private bool _isVisible = true;
    public bool IsVisible
    {
        get => _isVisible;
        set { _isVisible = value; Notify(); }
    }

    private bool _isInstalled;
    public bool IsInstalled
    {
        get => _isInstalled;
        set
        {
            _isInstalled = value;
            Notify();
            Notify(nameof(InstalledBadgeVisible));
        }
    }

    public bool InstalledBadgeVisible => IsInstalled;

    public event PropertyChangedEventHandler? PropertyChanged;
    private void Notify([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

/// <summary>
/// Обёртка для версии AE — используется в RadioButton-таблетках.
/// Может представлять как реально найденную установку (IsAvailable=true), так и
/// «слот» под версию, которой пока нет (IsAvailable=false, Installation=null).
/// </summary>
public class AeVersionPill : INotifyPropertyChanged
{
    public Services.AfterEffectsInstallation? Installation { get; set; }
    public string Version { get; }

    public AeVersionPill(string version, Services.AfterEffectsInstallation? installation = null)
    {
        Version = version;
        Installation = installation;
    }

    /// <summary>True, если AE этой версии реально установлен и путь известен.</summary>
    public bool IsAvailable => Installation != null;

    private bool _isSelected;
    public bool IsSelected
    {
        get => _isSelected;
        set
        {
            _isSelected = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(IsSelected)));
        }
    }

    /// <summary>Обновляет ссылку на установку и уведомляет об IsAvailable.</summary>
    public void SetInstallation(Services.AfterEffectsInstallation? ae)
    {
        Installation = ae;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(IsAvailable)));
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Installation)));
    }

    public event PropertyChangedEventHandler? PropertyChanged;
}
