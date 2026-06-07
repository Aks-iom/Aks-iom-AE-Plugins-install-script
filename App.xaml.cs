using System;
using System.Windows;
using AEPluginInstaller.Services;
using AEPluginInstaller.Services.Localization;
using AEPluginInstaller.Views;
using Microsoft.Extensions.DependencyInjection;
using Application = System.Windows.Application;

namespace AEPluginInstaller;

public partial class App : Application
{
    /// <summary>DI-контейнер. Создаётся в OnStartup, доступен через App.Services.</summary>
    public static IServiceProvider Services { get; private set; } = null!;

    // -----------------------------------------------------------------------
    // Мост совместимости со старым кодом (Views/*, кроме MainWindow).
    // Постепенно мигрируем потребителей на конструкторное внедрение
    // и удаляем эти свойства. Не использовать в новом коде.
    // -----------------------------------------------------------------------
    public static AppSettings Settings => Services.GetRequiredService<AppSettings>();
    public static DownloadCache Cache => Services.GetRequiredService<DownloadCache>();
    public static AeBlacklistStore Blacklist => Services.GetRequiredService<AeBlacklistStore>();
    public static UserProgress Progress => Services.GetRequiredService<UserProgress>();
    public static TelemetryManager Telemetry => Services.GetRequiredService<TelemetryManager>();

    protected override void OnStartup(StartupEventArgs e)
    {
        // Временно отключаем закрытие приложения после скрытия диалога
        this.ShutdownMode = ShutdownMode.OnExplicitShutdown;

        Services = BuildServiceProvider();

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
                var store = Services.GetRequiredService<ManualAePathStore>();
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

        var mainWindow = Services.GetRequiredService<MainWindow>();
        this.MainWindow = mainWindow;

        // Возвращаем стандартное поведение: закрытие при закрытии главного окна
        this.ShutdownMode = ShutdownMode.OnMainWindowClose;
        mainWindow.Show();
    }

    private static IServiceProvider BuildServiceProvider()
    {
        var services = new ServiceCollection();

        // Stores / settings (с состоянием — singleton).
        services.AddSingleton<AppSettings>();
        services.AddSingleton<DownloadCache>();
        services.AddSingleton<AeBlacklistStore>();
        services.AddSingleton<UserProgress>();
        services.AddSingleton<TelemetryManager>();
        services.AddSingleton<ConfigService>();
        services.AddSingleton<ManualAePathStore>();

        // Stateless утилиты — singleton ради единого инстанса, но безопасны transient.
        services.AddSingleton<GoogleDriveDownloader>();

        // Окна — transient: новый инстанс при каждом запросе.
        services.AddTransient<MainWindow>();

        return services.BuildServiceProvider();
    }
}
