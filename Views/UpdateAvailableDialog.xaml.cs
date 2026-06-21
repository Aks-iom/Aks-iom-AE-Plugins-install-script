using System;
using System.ComponentModel;
using System.Windows;
using AEPluginInstaller.Services.Updater;

namespace AEPluginInstaller.Views;

public partial class UpdateAvailableDialog : Window
{
    private readonly PortableAutoUpdater _updater;
    private readonly PortableAutoUpdater.UpdateInfo _info;
    private bool _downloading;

    /// <summary>true — пользователь нажал "Нет" (отказался от обновления).</summary>
    public bool UserDeclined { get; private set; }

    public UpdateAvailableDialog(PortableAutoUpdater updater, PortableAutoUpdater.UpdateInfo info)
    {
        InitializeComponent();
        Helpers.DarkTitleBar.Apply(this);
        _updater = updater;
        _info = info;
        MessageText.Text = $"Доступна новая версия {info.NewVersion}. Обновить?";
        Closing += OnClosing;
    }

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        // Запрещаем закрывать окно во время скачивания: иначе обновление прервётся,
        // а .bat не запустится — приложение останется на старой версии.
        if (_downloading) e.Cancel = true;
    }

    private async void Yes_Click(object sender, RoutedEventArgs e)
    {
        _downloading = true;
        SwitchToDownloadMode();

        var progress = new Progress<PortableAutoUpdater.DownloadProgress>(p =>
        {
            if (p.TotalBytes is long total && total > 0)
            {
                var pct = total == 0 ? 0 : p.BytesReceived * 100.0 / total;
                DownloadProgress.IsIndeterminate = false;
                DownloadProgress.Value = pct;
                ProgressText.Text =
                    $"{FormatBytes(p.BytesReceived)} / {FormatBytes(total)}  ({pct:F0}%)";
            }
            else
            {
                DownloadProgress.IsIndeterminate = true;
                ProgressText.Text = $"Скачано: {FormatBytes(p.BytesReceived)}";
            }
        });

        try
        {
            await _updater.StartUpdateAndExitAsync(_info, progress);
            // StartUpdateAndExitAsync вызывает Environment.Exit — сюда не дойдём.
        }
        catch (Exception ex)
        {
            _downloading = false;
            ProgressPanel.Visibility = Visibility.Collapsed;
            HeaderText.Text = "Ошибка обновления";
            MessageText.Text = HumanizeError(ex);
            YesBtn.Content = "Повторить";
            YesBtn.IsEnabled = true;
            NoBtn.Content = "Закрыть";
            NoBtn.IsEnabled = true;
        }
    }

    private static string HumanizeError(Exception ex)
    {
        // Разворачиваем цепочку — у сетевых ошибок настоящая причина обычно в InnerException.
        for (var e = ex; e != null; e = e.InnerException)
        {
            var msg = e.Message ?? string.Empty;
            if (e is System.Net.Http.HttpRequestException
                || e is System.Net.Sockets.SocketException
                || e is System.IO.IOException
                || msg.Contains("SSL", StringComparison.OrdinalIgnoreCase)
                || msg.Contains("TLS", StringComparison.OrdinalIgnoreCase))
            {
                return "Не удалось скачать обновление. Проверьте подключение к интернету "
                     + "и попробуйте ещё раз.";
            }
            if (e is OperationCanceledException)
                return "Скачивание было прервано. Попробуйте ещё раз.";
        }
        return "Не удалось обновить: " + ex.Message;
    }

    private void No_Click(object sender, RoutedEventArgs e)
    {
        if (_downloading) return;
        UserDeclined = true;
        DialogResult = false;
        Close();
    }

    private void SwitchToDownloadMode()
    {
        HeaderText.Text = "Загрузка обновления...";
        MessageText.Text = $"Скачивается версия {_info.NewVersion}. Не закрывайте окно.";
        ProgressPanel.Visibility = Visibility.Visible;
        DownloadProgress.IsIndeterminate = true;
        ProgressText.Text = "Подключение...";
        YesBtn.IsEnabled = false;
        NoBtn.IsEnabled = false;
    }

    private static string FormatBytes(long b)
    {
        if (b < 0) return "?";
        string[] u = { "Б", "КБ", "МБ", "ГБ" };
        double d = b; int i = 0;
        while (d >= 1024 && i < u.Length - 1) { d /= 1024; i++; }
        return $"{d:F1} {u[i]}";
    }
}
