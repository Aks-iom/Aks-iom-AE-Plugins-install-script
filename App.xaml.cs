using System.Windows;
using AEPluginInstaller.Services;
using AEPluginInstaller.Services.Localization;
using AEPluginInstaller.Views;
using Application = System.Windows.Application;

namespace AEPluginInstaller;

public partial class App : Application
{
    public static AppSettings Settings { get; private set; } = null!;
    public static DownloadCache Cache { get; private set; } = null!;
    public static AeBlacklistStore Blacklist { get; private set; } = null!;
    public static UserProgress Progress { get; private set; } = null!;
    public static TelemetryManager Telemetry { get; private set; } = null!;

    protected override void OnStartup(StartupEventArgs e)
    {
        // Временно отключаем закрытие приложения после скрытия диалога
        this.ShutdownMode = ShutdownMode.OnExplicitShutdown;

        Settings = new AppSettings();
        Cache = new DownloadCache();
        Blacklist = new AeBlacklistStore();
        Progress = new UserProgress();
        Telemetry = new TelemetryManager(Progress);

        L10n.Initialize(string.IsNullOrEmpty(Settings.Data.Language) ? null : Settings.Data.Language);

        if (Progress.Data.IsFirstLaunch)
        {
            var dialog = new TelemetryConsentDialog();
            dialog.ShowDialog();

            Progress.Data.IsTelemetryEnabled = dialog.IsConsentGiven;
            Progress.Data.IsFirstLaunch = false;
            Progress.Save();

            // Если пользователь указал путь к AE — сохраняем как ручной (он имеет приоритет).
            if (!string.IsNullOrWhiteSpace(dialog.SelectedAePath))
            {
                var store = new ManualAePathStore();
                var leaf = System.IO.Path.GetFileName(
                    dialog.SelectedAePath.TrimEnd('\\', '/')) ?? "";
                var m = System.Text.RegularExpressions.Regex.Match(leaf, @"(?:19|20)(\d{2})");
                // Ключ — двузначный мажор-код ("24"); если в имени папки нет года —
                // используем плейсхолдер "00", чтобы запись не была потеряна.
                var key = m.Success ? m.Groups[1].Value : "00";
                store.Set(key, dialog.SelectedAePath);
            }
        }

        base.OnStartup(e);

        var mainWindow = new MainWindow();
        this.MainWindow = mainWindow;
        
        // Возвращаем стандартное поведение: закрытие при закрытии главного окна
        this.ShutdownMode = ShutdownMode.OnMainWindowClose;
        mainWindow.Show();
    }
}
