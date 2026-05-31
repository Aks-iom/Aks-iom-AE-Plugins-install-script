using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using Application = System.Windows.Application;
using MessageBox = System.Windows.MessageBox;
using Button = System.Windows.Controls.Button;
using AEPluginInstaller.Models;
using AEPluginInstaller.Services;
using AEPluginInstaller.Services.Install;
using AEPluginInstaller.Services.Localization;
using AEPluginInstaller.ViewModels;

namespace AEPluginInstaller.Views;

public partial class MainWindow : Window
{
    private readonly ConfigService _configService = new();
    private readonly ObservableCollection<PluginConfig> _configs = new();
    private readonly ObservableCollection<AeVersionPill> _aeVersions = new();
    private readonly ObservableCollection<PluginRow> _allRows = new();   // полный список (для текущего конфига)
    private readonly ObservableCollection<PluginRow> _visibleRows = new(); // отфильтрованный для отображения
    private PluginConfig? _currentConfig;
    private bool _suppressSelectAllUpdate;

    private readonly string _installedDir = System.IO.Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "AEPluginInstaller", "installed");
    private readonly PluginInstallEngine _engine;
    private readonly ManualAePathStore _manualPaths = new();

    /// <summary>Полный диапазон версий AE, которые приложение всегда показывает в шапке.</summary>
    private static readonly string[] AeVersionRange = { "20", "21", "22", "23", "24", "25", "26" };

    public MainWindow()
    {
        InitializeComponent();
        Helpers.DarkTitleBar.Apply(this);
        _engine = new PluginInstallEngine(_installedDir);
        ConfigsCombo.ItemsSource = _configs;
        AeVersionPills.ItemsSource = _aeVersions;
        PluginsList.ItemsSource = _visibleRows;

        Loaded += (_, _) =>
        {
            LoadAeVersions();
            EnsureCatalogsImported();
            LoadConfigs();
            UpdateButtonsEnabled();
            UpdateFooter();
        };
    }

    // ============ AE: таблетки версий ============

    private void LoadAeVersions()
    {
        var foundMap = BuildFoundMap();
        _aeVersions.Clear();

        AeVersionPill? firstAvailable = null;
        foreach (var ver in AeVersionRange)
        {
            foundMap.TryGetValue(ver, out var installation);
            var pill = new AeVersionPill(ver, installation);
            pill.PropertyChanged += (_, e) =>
            {
                if (e.PropertyName == nameof(AeVersionPill.IsSelected) && pill.IsSelected)
                    RefreshInstalledStatus();
            };
            _aeVersions.Add(pill);
            if (installation != null && firstAvailable == null)
                firstAvailable = pill;
        }

        // Выбираем по умолчанию первую найденную; если нет ни одной — самую свежую (26)
        var toSelect = firstAvailable ?? _aeVersions[^1];
        toSelect.IsSelected = true;

        var availableCount = foundMap.Count;
        if (availableCount > 0)
        {
            AppendLog(L10n.T("log.found_ae", availableCount));
            foreach (var ae in foundMap.Values)
                AppendLog(L10n.T("log.ae_item", ae.Version, ae.InstallPath));
        }
        else
        {
            AppendLog(L10n.T("log.no_ae"));
        }
    }

    /// <summary>
    /// Сканирование + ручные пути, объединённые по ДВУЗНАЧНОМУ коду мажорной версии
    /// (MajorCode: "24", "25", ...). Именно по нему «таблетки» в шапке ("20".."26")
    /// сопоставляются с найденной установкой.
    ///
    /// Приоритет — у РУЧНЫХ путей: автоскан кладётся первым, ручные перезаписывают
    /// найденное автоматически. Это нужно, чтобы пользовательский выбор всегда
    /// побеждал, даже если на других дисках есть «стандартная» установка.
    /// </summary>
    private Dictionary<string, AfterEffectsInstallation> BuildFoundMap()
    {
        var map = new Dictionary<string, AfterEffectsInstallation>(StringComparer.OrdinalIgnoreCase);

        // 1) Автоскан по всем дискам — фоновый источник.
        foreach (var ae in AfterEffectsLocator.FindInstallations())
        {
            if (App.Blacklist.IsBlacklisted(ae.InstallPath)) continue;
            map[ae.MajorCode] = ae;
        }

        // 2) Ручные пути — перебивают автоскан (выше приоритет).
        foreach (var ae in _manualPaths.GetAll())
        {
            if (App.Blacklist.IsBlacklisted(ae.InstallPath)) continue;
            if (string.IsNullOrEmpty(ae.MajorCode)) continue;
            map[ae.MajorCode] = ae;
        }
        return map;
    }

    private AfterEffectsInstallation? GetSelectedAe()
        => _aeVersions.FirstOrDefault(v => v.IsSelected)?.Installation;

    /// <summary>
    /// Возвращает выбранную версию (строку); если AE для неё не найден — пытается
    /// проверить заново и при неудаче открывает диалог «Обзор...».
    /// Вернёт null, если пользователь отменил выбор.
    /// </summary>
    private AfterEffectsInstallation? EnsureSelectedAeAvailable()
    {
        var pill = _aeVersions.FirstOrDefault(v => v.IsSelected);
        if (pill == null)
        {
            AppMessageDialog.Warn(this, L10n.T("dlg.no_version.title"), L10n.T("dlg.no_version.text"));
            return null;
        }
        if (pill.Installation != null) return pill.Installation;

        // Повторный скан — может, AE поставили только что
        var map = BuildFoundMap();
        if (map.TryGetValue(pill.Version, out var freshly))
        {
            pill.SetInstallation(freshly);
            AppendLog($"  • Найдено заново: After Effects {pill.Version} → {freshly.InstallPath}");
            return freshly;
        }

        // Диалог
        var dlg = new AeNotFoundDialog(pill.Version) { Owner = this };
        var ok = dlg.ShowDialog() == true && !string.IsNullOrEmpty(dlg.SelectedPath);
        if (!ok) return null;

        var manual = new AfterEffectsInstallation
        {
            // Метку версии берём из имени выбранной папки (".../Adobe After Effects 2024" → "2024"),
            // чтобы корректно строились пути User Presets и подстановка {AE_VERSION}.
            // Если год в имени не распознан — откатываемся к "20" + код таблетки.
            Version = DeriveYearFromFolder(dlg.SelectedPath!, pill.Version),
            InstallPath = dlg.SelectedPath!
        };
        _manualPaths.Set(pill.Version, dlg.SelectedPath!);
        pill.SetInstallation(manual);
        AppendLog($"  • Путь указан вручную: After Effects {pill.Version} → {dlg.SelectedPath}");
        return manual;
    }

    /// <summary>
    /// Из выбранной вручную папки AE достаёт «годовую» метку версии.
    /// "...\Adobe After Effects 2025 (Beta)" → "2025"; если года нет — "20"+код таблетки.
    /// </summary>
    private static string DeriveYearFromFolder(string folder, string pillCode)
    {
        var leaf = System.IO.Path.GetFileName(folder.TrimEnd('\\', '/')) ?? "";
        var m = System.Text.RegularExpressions.Regex.Match(leaf, @"(?:19|20)\d{2}");
        if (m.Success) return m.Value;
        return pillCode.Length == 2 ? "20" + pillCode : pillCode;
    }

    /// <summary>
    /// Перепроверяет каждый плагин из текущего списка: есть ли свежий манифест
    /// с реально существующими артефактами. Выставляет IsInstalled на строках.
    /// </summary>
    private void RefreshInstalledStatus()
    {
        var ae = GetSelectedAe();
        if (ae == null)
        {
            foreach (var r in _allRows) r.IsInstalled = false;
            return;
        }

        // Эвристика для плагинов без манифеста (установлены вручную / другим инсталлером).
        InstalledPluginDetector? detector = null;
        try { detector = InstalledPluginDetector.Build(ae); } catch { }

        foreach (var r in _allRows)
        {
            var manifest = InstalledManifest.Read(_installedDir, r.Model.Name, ae.Version);
            var byManifest = manifest != null
                && manifest.Artifacts.Count > 0
                && InstalledManifest.ArtifactsPresent(manifest);

            if (byManifest)
            {
                r.IsInstalled = true;
                continue;
            }

            r.IsInstalled = detector != null && detector.IsInstalled(r.Model);
        }
    }

    // ============ Импорт встроенных каталогов ============

    private void EnsureCatalogsImported()
    {
        var existing = _configService.LoadAll()
            .Select(c => c.Name).ToHashSet(StringComparer.OrdinalIgnoreCase);

        var baseDir = AppContext.BaseDirectory;
        var basicPath = Path.Combine(baseDir, "Catalogs", "plugins.json");
        var extPath = Path.Combine(baseDir, "Catalogs", "extended_list.json");

        if (!existing.Contains("Основной набор"))
        {
            var c = CatalogImporter.ImportBasicCatalog(
                basicPath, "Основной набор",
                "Крупные плагины — Sapphire, Mocha, Trapcode, BCC и др.");
            if (c != null && c.Plugins.Count > 0)
            {
                _configService.Save(c);
                AppendLog($"Импортирован каталог «Основной набор»: {c.Plugins.Count} плагинов");
            }
        }

        if (!existing.Contains("Расширенный список"))
        {
            var c = CatalogImporter.ImportExtendedCatalog(
                extPath, "Расширенный список",
                "Малые плагины и скрипты.");
            if (c != null && c.Plugins.Count > 0)
            {
                _configService.Save(c);
                AppendLog($"Импортирован каталог «Расширенный список»: {c.Plugins.Count} плагинов");
            }
        }
    }

    // ============ Конфиги ============

    private void LoadConfigs()
    {
        _configs.Clear();
        foreach (var c in _configService.LoadAll())
            _configs.Add(c);

        if (_configs.Count > 0)
            ConfigsCombo.SelectedIndex = 0;
        UpdateFooter();
    }

    private void ConfigsCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        _currentConfig = ConfigsCombo.SelectedItem as PluginConfig;
        BindCurrentConfig();
        UpdateButtonsEnabled();
    }

    private void BindCurrentConfig()
    {
        _allRows.Clear();
        _visibleRows.Clear();

        if (_currentConfig == null) { UpdateCounters(); return; }

        foreach (var p in _currentConfig.Plugins)
        {
            var row = new PluginRow(p);
            row.PropertyChanged += (_, e) =>
            {
                if (e.PropertyName == nameof(PluginRow.IsSelected))
                    UpdateSelectAllCheckbox();
            };
            _allRows.Add(row);
        }
        ApplyFilter();
        UpdateCounters();
        RefreshInstalledStatus();
    }

    private void AdvancedBtn_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new AdvancedWindow(this, _currentConfig != null) { Owner = this };
        dlg.ShowDialog();
    }

    internal void AddConfigAndSelect(PluginConfig cfg)
    {
        _configService.Save(cfg);
        _configs.Add(cfg);
        ConfigsCombo.SelectedItem = cfg;
        UpdateFooter();
        AppendLog($"✔ Создан конфиг «{cfg.Name}»");
    }

    internal void UpdateExistingConfig(PluginConfig cfg, string oldName)
    {
        if (!string.Equals(oldName, cfg.Name, StringComparison.Ordinal))
            _configService.Rename(cfg, oldName);
        else
            _configService.Save(cfg);
        BindCurrentConfig();
        ConfigsCombo.Items.Refresh();
        AppendLog($"✔ Конфиг «{cfg.Name}» сохранён");
    }

    internal void NotifyBlacklistChanged() => LoadAeVersions();

    internal string GetNewConfigName()
    {
        var name = "Новый конфиг";
        var i = 2;
        while (_configs.Any(c => c.Name == name)) name = $"Новый конфиг {i++}";
        return name;
    }

    internal PluginConfig? CurrentConfig => _currentConfig;

    internal void DeleteConfigBtn_Click(object? sender = null, RoutedEventArgs? e = null)
    {
        if (_currentConfig == null) return;
        if (!AppMessageDialog.Confirm(this,
            L10n.T("dlg.del_config.title"),
            L10n.T("dlg.del_config.text", _currentConfig.Name))) return;

        _configService.Delete(_currentConfig);
        _configs.Remove(_currentConfig);
        _currentConfig = null;
        ConfigsCombo.SelectedIndex = _configs.Count > 0 ? 0 : -1;
        UpdateFooter();
    }

    // ============ Поиск ============

    private void SearchBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        SearchPlaceholder.Visibility = string.IsNullOrEmpty(SearchBox.Text)
            ? Visibility.Visible : Visibility.Collapsed;
        ApplyFilter();
    }

    private void ApplyFilter()
    {
        var q = SearchBox.Text?.Trim() ?? "";
        _visibleRows.Clear();
        foreach (var r in _allRows)
        {
            if (string.IsNullOrEmpty(q) ||
                r.Name.Contains(q, StringComparison.OrdinalIgnoreCase) ||
                r.Subtitle.Contains(q, StringComparison.OrdinalIgnoreCase))
            {
                _visibleRows.Add(r);
            }
        }
        UpdateCounters();
        UpdateSelectAllCheckbox();
    }

    // ============ Выбор: «выбрать все» + чекбоксы ============

    private void SelectAllCheck_Click(object sender, RoutedEventArgs e)
    {
        var target = SelectAllCheck.IsChecked == true;
        foreach (var r in _visibleRows) r.IsSelected = target;
        UpdateCounters();
    }

    private void PluginCheck_Click(object sender, RoutedEventArgs e)
    {
        UpdateSelectAllCheckbox();
        UpdateCounters();
    }

    private void UpdateSelectAllCheckbox()
    {
        if (_suppressSelectAllUpdate) return;
        _suppressSelectAllUpdate = true;
        try
        {
            if (_visibleRows.Count == 0) SelectAllCheck.IsChecked = false;
            else if (_visibleRows.All(r => r.IsSelected)) SelectAllCheck.IsChecked = true;
            else if (_visibleRows.Any(r => r.IsSelected)) SelectAllCheck.IsChecked = null; // intermediate
            else SelectAllCheck.IsChecked = false;
        }
        finally { _suppressSelectAllUpdate = false; }
    }

    private void UpdateCounters()
    {
        var total = _allRows.Count;
        var selected = _allRows.Count(r => r.IsSelected);
        var visible = _visibleRows.Count;
        var basePart = visible == total ? $"всего: {total}" : $"показано: {visible} из {total}";
        PluginsCountLabel.Text = selected > 0
            ? $"{basePart}  •  выбрано: {selected}"
            : basePart;
    }

    // ============ Установка ============

    private async void InstallSelectedBtn_Click(object sender, RoutedEventArgs e)
    {
        var selected = _allRows.Where(r => r.IsSelected).ToList();
        if (selected.Count == 0)
        {
            AppMessageDialog.Warn(this, L10n.T("dlg.no_selected.title"), L10n.T("dlg.no_selected.text"));
            return;
        }
        await InstallAsync(selected);
    }

    private async Task InstallAsync(List<PluginRow> rows)
    {
        var ae = EnsureSelectedAeAvailable();
        if (ae == null) return;

        // 1) Если AE запущен — попросить закрыть
        if (AeProcessChecker.IsAeRunning())
        {
            var dlg = new AeRunningDialog { Owner = this };
            dlg.ShowDialog();
            if (dlg.Result == AeRunningResult.Cancel) return;
            // Continue / Skip — продолжаем
        }

        // 2) Резюме перед установкой
        var targetDrive = Path.GetPathRoot(ae.InstallPath) ?? "C:\\";
        var summary = new InstallSummaryDialog(rows.Select(r => r.Model).ToList(), App.Cache, targetDrive)
        {
            Owner = this
        };
        summary.ShowDialog();
        if (!summary.Confirmed) return;

        if (_currentConfig != null)
        {
            _currentConfig.Plugins = _allRows.Select(r => r.Model).ToList();
            _configService.Save(_currentConfig);
        }

        SetUiBusy(true);
        HideLogEmptyHint();
        var rootTempDir = Path.Combine(Path.GetTempPath(), $"aeplugin_dl_{Guid.NewGuid():N}");
        Directory.CreateDirectory(rootTempDir);

        AppendLog(L10n.T("log.install_begin", ae.ToString()));

        using var downloader = new GoogleDriveDownloader();

        int ok = 0, fail = 0;
        for (int i = 0; i < rows.Count; i++)
        {
            var row = rows[i];
            var plugin = row.Model;
            ProgressText.Text = $"[{i + 1}/{rows.Count}] {plugin.Name}";
            AppendLog("");
            AppendLog($"▸ {plugin.Name}" +
                (string.IsNullOrEmpty(plugin.Version) ? "" : $"  v{plugin.Version}") +
                (string.IsNullOrEmpty(plugin.Size) ? "" : $"  ({plugin.Size})"));

            try
            {
                var pluginSrcDir = Path.Combine(rootTempDir, SafeFolder(plugin.Name));
                Directory.CreateDirectory(pluginSrcDir);

                var files = await DownloadPluginFilesAsync(
                    downloader, plugin, pluginSrcDir, $"{i + 1}/{rows.Count}");

                if (files.Count == 0)
                {
                    AppendLog(L10n.T("log.empty_link"));
                    fail++; continue;
                }

                var stepsJson = BuildStepsForPlugin(plugin, files);

                var ctx = new InstallContext
                {
                    PluginName = plugin.Name,
                    AeVersion = ae.Version,
                    SrcDir = pluginSrcDir,
                    Paths = DefaultPaths.Build(ae.Version, customInstallPath: ae.InstallPath),
                    Log = msg => Dispatcher.Invoke(() => AppendLog(msg))
                };

                AppendLog(L10n.T("log.installing"));
                var success = await Task.Run(() => _engine.Install(stepsJson, ctx, plugin.Version));
                if (success)
                {
                    if (!string.IsNullOrEmpty(plugin.Warning))
                        AppendLog($"  ⚠ {plugin.Warning}");
                    ok++;
                }
                else fail++;
            }
            catch (Exception ex)
            {
                AppendLog(L10n.T("log.error", ex.Message));
                fail++;
            }
        }

        try { Directory.Delete(rootTempDir, recursive: true); } catch { /* ignore */ }

        AppendLog("");
        AppendLog(L10n.T("log.install_end", ok, fail));
        ProgressText.Text = L10n.T("progress.done", ok, fail);
        MainProgress.Value = 0;
        SetUiBusy(false);
        RefreshInstalledStatus();

        // Send Telemetry
        _ = App.Telemetry.SendLogAsync(LogText.Text, fail == 0);
    }

    /// <summary>Скачивает все файлы плагина в pluginSrcDir и возвращает список с типами/целями.</summary>
    private async Task<List<DownloadedFile>> DownloadPluginFilesAsync(
        GoogleDriveDownloader downloader, Plugin plugin, string pluginSrcDir, string counter)
    {
        var result = new List<DownloadedFile>();

        // url, желаемое имя, ожидаемый хеш, метка для лога
        async Task<string> Acquire(string url, string suggestedName, string expectedHash, string label)
        {
            var desired = Path.Combine(pluginSrcDir, suggestedName);
            var fileId = GoogleDriveDownloader.ExtractFileId(url);

            // 1) Проверка кэша
            if (!string.IsNullOrEmpty(fileId))
            {
                var cached = App.Cache.TryGet(fileId, suggestedName);
                if (cached != null && (string.IsNullOrEmpty(expectedHash) || VerifyHash(cached, expectedHash)))
                {
                    File.Copy(cached, desired, overwrite: true);
                    AppendLog(L10n.T("log.cache_hit", suggestedName));
                    return desired;
                }
            }

            // 2) Скачивание
            AppendLog(L10n.T("log.downloading", label));
            var progress = new Progress<DownloadProgress>(pr =>
            {
                MainProgress.Value = pr.Percent;
                ProgressText.Text = $"[{counter}] {plugin.Name} — {FormatBytes(pr.Bytes)}" +
                    (pr.Total > 0 ? $" / {FormatBytes(pr.Total)} ({pr.Percent:F0}%)" : "");
            });

            var dl = await downloader.DownloadAsync(url, pluginSrcDir, progress, CancellationToken.None);
            if (!string.Equals(dl, desired, StringComparison.OrdinalIgnoreCase))
            {
                if (File.Exists(desired)) File.Delete(desired);
                File.Move(dl, desired);
            }
            AppendLog(L10n.T("log.downloaded", Path.GetFileName(desired),
                FormatBytes(new FileInfo(desired).Length)));

            // 3) Проверка хеша (если задан)
            if (!string.IsNullOrEmpty(expectedHash))
            {
                AppendLog(L10n.T("log.check_hash"));
                if (!VerifyHash(desired, expectedHash, out var actual))
                {
                    AppendLog(L10n.T("log.hash_fail", expectedHash, actual));
                    File.Delete(desired);
                    throw new Exception($"Hash mismatch for {suggestedName}");
                }
                AppendLog(L10n.T("log.hash_ok"));
            }

            // 4) Сохраняем в кэш
            if (!string.IsNullOrEmpty(fileId))
            {
                try { App.Cache.Put(fileId, desired, suggestedName); } catch { }
            }
            return desired;
        }

        if (plugin.Files.Count > 0)
        {
            int idx = 0;
            foreach (var f in plugin.Files)
            {
                idx++;
                if (string.IsNullOrWhiteSpace(f.GoogleDriveUrl)) continue;
                var fname = !string.IsNullOrEmpty(f.FileName)
                    ? f.FileName : DefaultFileNameFor(f.Type, idx);
                var path = await Acquire(f.GoogleDriveUrl, fname, f.Hash, $"{f.Type}: {fname}");
                result.Add(new DownloadedFile(path, fname, f.Type, f.TargetPath));
            }
        }
        else if (!string.IsNullOrWhiteSpace(plugin.GoogleDriveUrl))
        {
            var fname = DefaultFileNameFor(plugin.Type, 1);
            var path = await Acquire(plugin.GoogleDriveUrl, fname, plugin.Hash, fname);
            result.Add(new DownloadedFile(path, fname, plugin.Type, plugin.CustomTargetFolder));
        }

        return result;
    }

    private static bool VerifyHash(string file, string expected) =>
        VerifyHash(file, expected, out _);

    private static bool VerifyHash(string file, string expected, out string actual)
    {
        actual = "";
        try
        {
            var algo = expected.Length switch
            {
                32 => "MD5",
                40 => "SHA1",
                64 => "SHA256",
                _ => null
            };
            if (algo == null) return true;  // неизвестный формат — пропускаем
            actual = FileHashing.ComputeHex(file, algo);
            return string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    private static string DefaultFileNameFor(PluginType type, int idx) => type switch
    {
        PluginType.Archive => $"archive_{idx}.zip",
        PluginType.Installer => $"setup_{idx}.exe",
        PluginType.RegFile => $"keys_{idx}.reg",
        PluginType.Plugin => $"plugin_{idx}.aex",
        PluginType.Script => $"script_{idx}.jsx",
        PluginType.ScriptUI => $"scriptui_{idx}.jsx",
        PluginType.Preset => $"preset_{idx}.ffx",
        _ => $"file_{idx}.bin"
    };

    /// <summary>Собирает install_steps JSON из списка скачанных файлов.</summary>
    private static string BuildStepsForPlugin(Plugin plugin, List<DownloadedFile> files)
    {
        var steps = new List<object>();
        foreach (var f in files)
        {
            var src = "{SRC_DIR}/" + f.FileName;
            var target = NormalizeTarget(f.TargetPath);
            var actualType = f.Type == PluginType.Auto ? InferType(f.FileName) : f.Type;

            switch (actualType)
            {
                case PluginType.Archive:
                    // Инсталлятор из каталога: распаковать во временную папку и запустить
                    // указанный в bat_path файл, а не раскладывать содержимое по Plug-ins.
                    if (!string.IsNullOrEmpty(plugin.RunAfterExtract))
                    {
                        var stageDir = "{SRC_DIR}/_pkg";
                        var inner = plugin.RunAfterExtract.Replace('\\', '/').TrimStart('/');
                        steps.Add(new { type = "extract_zip", source = src, target = stageDir });
                        steps.Add(new { type = "run_exe", path = $"{stageDir}/{inner}", wait = true });
                        break;
                    }
                    steps.Add(new
                    {
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

                case PluginType.ScriptUI:
                    steps.Add(new { type = "copy_file", source = src, target = string.IsNullOrEmpty(target) ? "{SCRIPTS_DIR}" : target });
                    break;

                case PluginType.Script:
                    steps.Add(new { type = "copy_file", source = src, target = string.IsNullOrEmpty(target) ? "{AE_BASE}/Support Files/Scripts" : target });
                    break;

                case PluginType.Preset:
                    steps.Add(new { type = "copy_file", source = src, target = string.IsNullOrEmpty(target) ? "{PRESETS_DIR}" : target });
                    break;

                case PluginType.Plugin:
                default:
                    steps.Add(new { type = "copy_file", source = src, target = string.IsNullOrEmpty(target) ? "{PLUGINS_DIR}" : target });
                    break;
            }
        }
        return System.Text.Json.JsonSerializer.Serialize(steps);
    }

    private static PluginType InferType(string fileName)
    {
        var ext = Path.GetExtension(fileName).ToLowerInvariant();
        return ext switch
        {
            ".zip" or ".rar" or ".7z" => PluginType.Archive,
            ".exe" => PluginType.Installer,
            ".reg" => PluginType.RegFile,
            ".aex" or ".plugin" or ".dll" => PluginType.Plugin,
            ".jsxbin" or ".jsx" => fileName.ToLowerInvariant().Contains("panel") || fileName.ToLowerInvariant().Contains("ui")
                ? PluginType.ScriptUI : PluginType.Script,
            ".ffx" => PluginType.Preset,
            _ => PluginType.Plugin
        };
    }

    private static string NormalizeTarget(string raw)
    {
        if (string.IsNullOrEmpty(raw)) return "";
        // Те же подстановки, что были в PluginInstaller — поддерживаем старые конфиги
        return raw
            .Replace("{plugins}", "{PLUGINS_DIR}", StringComparison.OrdinalIgnoreCase)
            .Replace("{scripts}", "{AE_BASE}/Support Files/Scripts", StringComparison.OrdinalIgnoreCase)
            .Replace("{scriptui}", "{SCRIPTS_DIR}", StringComparison.OrdinalIgnoreCase)
            .Replace("{presets}", "{PRESETS_DIR}", StringComparison.OrdinalIgnoreCase)
            .Replace("{ae}", "{AE_BASE}", StringComparison.OrdinalIgnoreCase);
    }

    private static string SafeFolder(string s)
    {
        var sb = new System.Text.StringBuilder(s.Length);
        foreach (var ch in s)
            sb.Append(char.IsLetterOrDigit(ch) || ch is '_' or '-' or '.' ? ch : '_');
        return sb.ToString();
    }

    private record DownloadedFile(string FullPath, string FileName, PluginType Type, string TargetPath);

    // ============ UI helpers ============

    private void SetUiBusy(bool busy)
    {
        InstallAllBtn.IsEnabled = !busy;
        AdvancedBtn.IsEnabled = !busy;
        ConfigsCombo.IsEnabled = !busy;
        AeVersionPills.IsEnabled = !busy;
        SearchBox.IsEnabled = !busy;
        PluginsList.IsEnabled = !busy;
    }

    private void UpdateButtonsEnabled()
    {
        var hasConfig = _currentConfig != null;
        InstallAllBtn.IsEnabled = hasConfig;
    }

    private void UpdateFooter()
    {
        ConfigsCountLabel.Text = $"{_configs.Count} конфиг(ов)";
    }

    private void AppendLog(string line)
    {
        HideLogEmptyHint();
        var ts = DateTime.Now.ToString("HH:mm:ss");
        LogText.Text += $"[{ts}]  {line}\n";
        LogScroll.ScrollToEnd();
    }

    private void HideLogEmptyHint()
    {
        if (LogEmptyHint.Visibility != Visibility.Collapsed)
            LogEmptyHint.Visibility = Visibility.Collapsed;
    }

    private void ClearLogBtn_Click(object sender, RoutedEventArgs e)
    {
        LogText.Text = "";
        LogEmptyHint.Visibility = Visibility.Visible;
    }

    private void ConfigPathLink_Click(object sender, MouseButtonEventArgs e)
    {
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = _configService.ConfigsDirectory,
                UseShellExecute = true
            });
        }
        catch { /* ignore */ }
    }

    private static string FormatBytes(long b)
    {
        if (b < 0) return "?";
        string[] u = { "Б", "КБ", "МБ", "ГБ" };
        double d = b; int i = 0;
        while (d >= 1024 && i < u.Length - 1) { d /= 1024; i++; }
        return $"{d:F1} {u[i]}";
    }

    // ============ Импорт / Экспорт конфигов ============

    internal void ImportConfigBtn_Click(object? sender = null, RoutedEventArgs? e = null)
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = L10n.T("dlg.imp.choose"),
            Filter = "JSON config (*.json)|*.json|All files (*.*)|*.*"
        };
        if (dlg.ShowDialog(this) != true) return;
        try
        {
            var raw = File.ReadAllText(dlg.FileName);
            var imported = System.Text.Json.JsonSerializer.Deserialize<PluginConfig>(
                raw,
                new System.Text.Json.JsonSerializerOptions
                {
                    Converters = { new System.Text.Json.Serialization.JsonStringEnumConverter() }
                });
            if (imported == null || string.IsNullOrEmpty(imported.Name))
                throw new Exception("invalid");

            // Дубликат имени?
            if (_configs.Any(c => string.Equals(c.Name, imported.Name, StringComparison.OrdinalIgnoreCase)))
            {
                if (!AppMessageDialog.Confirm(this, L10n.T("dlg.imp.title"),
                    L10n.T("dlg.imp.dup", imported.Name)))
                    return;
                var existing = _configs.First(c => string.Equals(c.Name, imported.Name, StringComparison.OrdinalIgnoreCase));
                _configService.Delete(existing);
                _configs.Remove(existing);
            }

            _configService.Save(imported);
            _configs.Add(imported);
            ConfigsCombo.SelectedItem = imported;
            AppendLog(L10n.T("log.config_saved", imported.Name));
        }
        catch
        {
            AppMessageDialog.Warn(this, L10n.T("dlg.imp.title"), L10n.T("dlg.imp.bad"));
        }
    }

    internal void ExportConfigBtn_Click(object? sender = null, RoutedEventArgs? e = null)
    {
        if (_currentConfig == null) return;
        var dlg = new Microsoft.Win32.SaveFileDialog
        {
            Title = L10n.T("dlg.exp.choose"),
            Filter = "JSON config (*.json)|*.json",
            FileName = _currentConfig.Name + ".json"
        };
        if (dlg.ShowDialog(this) != true) return;
        try
        {
            File.WriteAllText(dlg.FileName, System.Text.Json.JsonSerializer.Serialize(_currentConfig,
                new System.Text.Json.JsonSerializerOptions
                {
                    WriteIndented = true,
                    Converters = { new System.Text.Json.Serialization.JsonStringEnumConverter() }
                }));
            AppendLog(L10n.T("dlg.exp.ok", dlg.FileName));
        }
        catch (Exception ex)
        {
            AppMessageDialog.Warn(this, L10n.T("header.config.export"), ex.Message);
        }
    }

    // ============ Сохранение лога ============

    private void SaveLogBtn_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new Microsoft.Win32.SaveFileDialog
        {
            Title = L10n.T("dlg.log_save.choose"),
            Filter = "Text file (*.txt)|*.txt|Log file (*.log)|*.log|All files (*.*)|*.*",
            FileName = $"aeinstaller-log-{DateTime.Now:yyyy-MM-dd_HHmm}.txt"
        };
        if (dlg.ShowDialog(this) != true) return;
        try { File.WriteAllText(dlg.FileName, LogText.Text); }
        catch (Exception ex)
        {
            AppMessageDialog.Warn(this, L10n.T("log.save"), ex.Message);
        }
    }

    // ============ Контекстное меню AE-таблетки ============

    private void AePill_RightClick(object sender, MouseButtonEventArgs e)
    {
        if (sender is not System.Windows.Controls.RadioButton rb || rb.Tag is not AeVersionPill pill) return;
        if (pill.Installation == null) return;

        var menu = new System.Windows.Controls.ContextMenu();
        var path = pill.Installation.InstallPath;

        var openItem = new System.Windows.Controls.MenuItem { Header = L10n.T("ctx.show_path") };
        openItem.Click += (_, _) =>
        {
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = path,
                    UseShellExecute = true
                });
            }
            catch { }
        };
        var hideItem = new System.Windows.Controls.MenuItem { Header = L10n.T("ctx.hide_ae") };
        hideItem.Click += (_, _) =>
        {
            App.Blacklist.Add(path);
            LoadAeVersions();
            RefreshInstalledStatus();
        };
        menu.Items.Add(openItem);
        menu.Items.Add(hideItem);
        menu.IsOpen = true;
    }

    // ============ Хоткеи ============

    private void Hotkey_SelectAll(object sender, System.Windows.Input.ExecutedRoutedEventArgs e)
    {
        var target = !_visibleRows.All(r => r.IsSelected);
        foreach (var r in _visibleRows) r.IsSelected = target;
        UpdateCounters();
        UpdateSelectAllCheckbox();
    }
    private void Hotkey_Find(object sender, System.Windows.Input.ExecutedRoutedEventArgs e)
    {
        SearchBox.Focus();
        SearchBox.SelectAll();
    }
    private async void Hotkey_Install(object sender, System.Windows.Input.ExecutedRoutedEventArgs e)
    {
        var selected = _allRows.Where(r => r.IsSelected).ToList();
        if (selected.Count == 0) return;
        await InstallAsync(selected);
    }
    private void Hotkey_SaveLog(object sender, System.Windows.Input.ExecutedRoutedEventArgs e)
        => SaveLogBtn_Click(sender, e);
    private void Hotkey_ExportConfig(object sender, System.Windows.Input.ExecutedRoutedEventArgs e)
        => ExportConfigBtn_Click(sender, e);
    private void Hotkey_ImportConfig(object sender, System.Windows.Input.ExecutedRoutedEventArgs e)
        => ImportConfigBtn_Click(sender, e);
    private void Hotkey_Settings(object sender, System.Windows.Input.ExecutedRoutedEventArgs e)
        => AdvancedBtn_Click(sender, e);
}
