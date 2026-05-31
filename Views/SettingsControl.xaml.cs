using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Windows;
using System.Windows.Controls;
using AEPluginInstaller.Services;
using AEPluginInstaller.Services.Localization;
using Button = System.Windows.Controls.Button;

namespace AEPluginInstaller.Views;

/// <summary>
/// Одна строка в списке путей к AE. Хранит и редактирует путь, помнит, был ли
/// он добавлен пользователем (тогда его можно убрать) или найден автоматически.
/// </summary>
public class AePathItem : INotifyPropertyChanged
{
    /// <summary>Двузначный мажор-код ("24"). Может быть пустым для новых ручных
    /// записей до того, как пользователь выберет папку.</summary>
    public string MajorCode { get; set; } = "";

    /// <summary>Метка версии для UI: «2024», «—» если код неизвестен.</summary>
    public string VersionLabel { get; set; } = "—";

    private string _path = "";
    public string Path
    {
        get => _path;
        set { _path = value ?? ""; Notify(); }
    }

    /// <summary>true — добавлено пользователем (или отредактировано); можно удалить.</summary>
    public bool IsManual { get; set; }

    public bool CanRemove => IsManual;
    public bool IsReadOnly => !IsManual;

    public string SourceLabel => IsManual
        ? L10n.T("settings.aepaths.source.manual")
        : L10n.T("settings.aepaths.source.auto");

    public event PropertyChangedEventHandler? PropertyChanged;
    private void Notify([CallerMemberName] string? n = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
}

public partial class SettingsControl : System.Windows.Controls.UserControl
{
    private readonly AppSettings _settings;
    private readonly DownloadCache _cache;
    private readonly AeBlacklistStore _blacklist;
    private readonly UserProgress _progress;
    private readonly ManualAePathStore _manualPaths = new();
    private readonly ObservableCollection<string> _blacklistItems = new();
    private readonly ObservableCollection<AePathItem> _aePathRows = new();
    private string _initialLang;

    public event Action? OnBlacklistChanged;

    /// <summary>Поднимается, когда пользователь поменял/добавил/удалил пути к AE,
    /// чтобы MainWindow перестроил «таблетки» версий.</summary>
    public event Action? OnAePathsChanged;

    public SettingsControl()
    {
        InitializeComponent();

        _settings = App.Settings;
        _cache = App.Cache;
        _blacklist = App.Blacklist;
        _progress = App.Progress;
        _initialLang = _settings.Data.Language;

        // Телеметрия
        UserIdBox.Text = _progress.Data.UserId;
        TelemetryCheck.IsChecked = _progress.Data.IsTelemetryEnabled;

        // Языки
        LangCombo.Items.Add(new ComboBoxItem { Content = L10n.T("settings.lang.auto"), Tag = "" });
        LangCombo.Items.Add(new ComboBoxItem { Content = L10n.T("settings.lang.ru"), Tag = "ru" });
        LangCombo.Items.Add(new ComboBoxItem { Content = L10n.T("settings.lang.en"), Tag = "en" });
        LangCombo.SelectedIndex = (_settings.Data.Language) switch
        {
            "ru" => 1, "en" => 2, _ => 0
        };
        LangCombo.SelectionChanged += LangCombo_SelectionChanged;

        // Кэш
        UpdateCacheSize();

        // Пути к AE
        AePathsItems.ItemsSource = _aePathRows;
        ReloadAePaths();

        // Blacklist
        BlacklistItems.ItemsSource = _blacklistItems;
        ReloadBlacklist();
    }

    // ───────────── Пути к AE ─────────────

    private void ReloadAePaths()
    {
        _aePathRows.Clear();

        // Manual идут первыми и имеют приоритет — их отображаем как «вручную».
        var manualKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var ae in _manualPaths.GetAll())
        {
            _aePathRows.Add(new AePathItem
            {
                MajorCode = ae.MajorCode,
                VersionLabel = string.IsNullOrEmpty(ae.Version) ? "—" : ae.Version,
                Path = ae.InstallPath,
                IsManual = true
            });
            if (!string.IsNullOrEmpty(ae.MajorCode))
                manualKeys.Add(ae.MajorCode);
        }

        // Auto добавляем только те, для которых нет ручного перекрытия.
        foreach (var ae in AfterEffectsLocator.FindInstallations())
        {
            if (manualKeys.Contains(ae.MajorCode)) continue;
            _aePathRows.Add(new AePathItem
            {
                MajorCode = ae.MajorCode,
                VersionLabel = string.IsNullOrEmpty(ae.Version) ? "—" : ae.Version,
                Path = ae.InstallPath,
                IsManual = false
            });
        }

        AePathsEmptyText.Visibility = _aePathRows.Count == 0
            ? Visibility.Visible : Visibility.Collapsed;
    }

    private void AddAePathBtn_Click(object sender, RoutedEventArgs e)
    {
        var path = AskFolder();
        if (string.IsNullOrEmpty(path)) return;

        if (!Directory.Exists(System.IO.Path.Combine(path, "Support Files")))
        {
            AppMessageDialog.Warn(Window.GetWindow(this),
                L10n.T("settings.aepaths"),
                L10n.T("settings.aepaths.bad_folder"));
            return;
        }

        var (label, code) = DeriveVersionLabel(path);
        var key = string.IsNullOrEmpty(code) ? "00" : code;
        _manualPaths.Set(key, path);

        ReloadAePaths();
        OnAePathsChanged?.Invoke();
        AppMessageDialog.Info(Window.GetWindow(this),
            L10n.T("settings.aepaths"),
            L10n.T("settings.aepaths.added", path));
    }

    private void BrowseAePathBtn_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button btn || btn.Tag is not AePathItem item) return;

        var picked = AskFolder(item.Path);
        if (string.IsNullOrEmpty(picked)) return;

        if (!Directory.Exists(System.IO.Path.Combine(picked, "Support Files")))
        {
            AppMessageDialog.Warn(Window.GetWindow(this),
                L10n.T("settings.aepaths"),
                L10n.T("settings.aepaths.bad_folder"));
            return;
        }

        // Любая правка в SettingsControl переводит запись в «ручную»: сохраняем в стор.
        var (label, code) = DeriveVersionLabel(picked);
        var key = !string.IsNullOrEmpty(code) ? code
                : !string.IsNullOrEmpty(item.MajorCode) ? item.MajorCode
                : "00";

        _manualPaths.Set(key, picked);
        ReloadAePaths();
        OnAePathsChanged?.Invoke();
    }

    private void RemoveAePathBtn_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button btn || btn.Tag is not AePathItem item) return;
        if (!item.IsManual) return;

        var key = string.IsNullOrEmpty(item.MajorCode) ? "00" : item.MajorCode;
        _manualPaths.Remove(key);
        ReloadAePaths();
        OnAePathsChanged?.Invoke();
    }

    private void RescanAePathsBtn_Click(object sender, RoutedEventArgs e)
    {
        var found = AfterEffectsLocator.FindInstallations();
        ReloadAePaths();
        OnAePathsChanged?.Invoke();
        AppMessageDialog.Info(Window.GetWindow(this),
            L10n.T("settings.aepaths"),
            L10n.T("settings.aepaths.rescanned", found.Count));
    }

    private string AskFolder(string initial = "")
    {
        var dlg = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = L10n.T("settings.aepaths.hint"),
            UseDescriptionForTitle = true,
            ShowNewFolderButton = false
        };
        if (!string.IsNullOrEmpty(initial) && Directory.Exists(initial))
            dlg.SelectedPath = initial;
        return dlg.ShowDialog() == System.Windows.Forms.DialogResult.OK ? dlg.SelectedPath : "";
    }

    private static (string label, string code) DeriveVersionLabel(string folder)
    {
        var leaf = System.IO.Path.GetFileName(folder.TrimEnd('\\', '/')) ?? "";
        var m = System.Text.RegularExpressions.Regex.Match(leaf, @"(?:19|20)(\d{2})");
        return m.Success
            ? (m.Value, m.Groups[1].Value)
            : ("—", "");
    }

    // ───────────── Остальные секции (без изменений) ─────────────

    private void UpdateCacheSize()
    {
        var bytes = _cache.GetTotalSize();
        CacheSizeText.Text = L10n.T("settings.cache.size", FormatBytes(bytes));
    }

    private void ReloadBlacklist()
    {
        _blacklistItems.Clear();
        foreach (var p in _blacklist.All().OrderBy(s => s))
            _blacklistItems.Add(p);
        BlacklistEmptyText.Visibility = _blacklistItems.Count == 0
            ? Visibility.Visible : Visibility.Collapsed;
    }

    private void LangCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (LangCombo.SelectedItem is not ComboBoxItem item) return;
        var newLang = item.Tag?.ToString() ?? "";
        _settings.Data.Language = newLang;
        _settings.Save();
        if (newLang != _initialLang)
        {
            RestartHint.Visibility = Visibility.Visible;
        }
    }

    private void CopyUserIdBtn_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            System.Windows.Clipboard.SetText(_progress.Data.UserId);
            AppMessageDialog.Info(Window.GetWindow(this), L10n.T("settings.telemetry"), L10n.T("settings.telemetry.copied"));
        }
        catch { }
    }

    private void TelemetryCheck_Click(object sender, RoutedEventArgs e)
    {
        _progress.Data.IsTelemetryEnabled = TelemetryCheck.IsChecked == true;
        _progress.Save();
    }

    private void ClearCacheBtn_Click(object sender, RoutedEventArgs e)
    {
        _cache.Clear();
        UpdateCacheSize();
        AppMessageDialog.Info(Window.GetWindow(this), L10n.T("settings.cache"), L10n.T("settings.cache.cleared"));
    }

    private void RestoreBtn_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button b && b.Tag is string path)
        {
            _blacklist.Remove(path);
            ReloadBlacklist();
            OnBlacklistChanged?.Invoke();
        }
    }

    private static string FormatBytes(long b)
    {
        if (b <= 0) return "0 Б";
        string[] u = { "Б", "КБ", "МБ", "ГБ" };
        double d = b; int i = 0;
        while (d >= 1024 && i < u.Length - 1) { d /= 1024; i++; }
        return $"{d:F1} {u[i]}";
    }
}
