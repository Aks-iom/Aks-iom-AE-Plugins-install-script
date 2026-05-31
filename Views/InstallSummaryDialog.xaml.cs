using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Windows;
using AEPluginInstaller.Models;
using AEPluginInstaller.Services;
using AEPluginInstaller.Services.Localization;

namespace AEPluginInstaller.Views;

public class SummaryRow
{
    public string Name { get; set; } = "";
    public string SizeText { get; set; } = "";
    public string StatusText { get; set; } = "";
}

public partial class InstallSummaryDialog : Window
{
    public bool Confirmed { get; private set; }
    private readonly ObservableCollection<SummaryRow> _rows = new();

    public InstallSummaryDialog(List<Plugin> plugins, DownloadCache cache, string targetDrive)
    {
        InitializeComponent();
        AEPluginInstaller.Helpers.DarkTitleBar.Apply(this);

        long totalToDownload = 0;
        foreach (var p in plugins)
        {
            var row = new SummaryRow
            {
                Name = p.Name + (string.IsNullOrEmpty(p.Version) ? "" : $"  v{p.Version}"),
                SizeText = string.IsNullOrEmpty(p.Size) ? "—" : p.Size
            };

            // Проверяем кэш — пометить, что не нужно качать
            bool fromCache = false;
            if (p.Files.Count > 0)
            {
                fromCache = p.Files.All(f =>
                {
                    var id = GoogleDriveDownloader.ExtractFileId(f.GoogleDriveUrl);
                    if (string.IsNullOrEmpty(id)) return false;
                    var fname = string.IsNullOrEmpty(f.FileName) ? "file.bin" : f.FileName;
                    return cache.TryGet(id, fname) != null;
                });
            }
            else if (!string.IsNullOrEmpty(p.GoogleDriveUrl))
            {
                var id = GoogleDriveDownloader.ExtractFileId(p.GoogleDriveUrl);
                if (!string.IsNullOrEmpty(id))
                {
                    // имя файла мы не знаем — но кэш привязан к id+имя, придумаем общее
                    fromCache = cache.TryGet(id!, "file.bin") != null;
                }
            }

            row.StatusText = fromCache ? L10n.T("dlg.summary.cached") : "";
            if (!fromCache)
                totalToDownload += EstimateSize(p.Size);
            _rows.Add(row);
        }

        PluginsList.ItemsSource = _rows;
        SubtitleText.Text = L10n.T("dlg.summary.subtitle", plugins.Count);
        TotalSizeText.Text = FormatBytes(totalToDownload);

        // Свободное место
        if (!string.IsNullOrEmpty(targetDrive))
        {
            try
            {
                var di = new DriveInfo(targetDrive);
                FreeSpaceLabel.Text = L10n.T("dlg.summary.free_space", targetDrive);
                FreeSpaceText.Text = FormatBytes(di.AvailableFreeSpace);
                // Сравниваем грубо: место для скачивания + ещё столько же на временную распаковку
                if (totalToDownload * 2 > di.AvailableFreeSpace)
                    NotEnoughHint.Visibility = Visibility.Visible;
            }
            catch
            {
                FreeSpaceLabel.Text = L10n.T("dlg.summary.free_space", targetDrive);
                FreeSpaceText.Text = "?";
            }
        }
    }

    /// <summary>Грубо: "~3,2 GB" → ~3.2 * 1024^3.</summary>
    private static long EstimateSize(string size)
    {
        if (string.IsNullOrEmpty(size)) return 0;
        var m = Regex.Match(size, @"([\d\.,]+)\s*(GB|MB|KB)", RegexOptions.IgnoreCase);
        if (!m.Success) return 0;
        if (!double.TryParse(m.Groups[1].Value.Replace(',', '.'),
            System.Globalization.NumberStyles.Float,
            System.Globalization.CultureInfo.InvariantCulture, out var num))
            return 0;
        var unit = m.Groups[2].Value.ToUpperInvariant();
        return unit switch
        {
            "GB" => (long)(num * 1024L * 1024L * 1024L),
            "MB" => (long)(num * 1024L * 1024L),
            "KB" => (long)(num * 1024L),
            _ => 0
        };
    }

    private static string FormatBytes(long b)
    {
        if (b <= 0) return "—";
        string[] u = { "Б", "КБ", "МБ", "ГБ" };
        double d = b; int i = 0;
        while (d >= 1024 && i < u.Length - 1) { d /= 1024; i++; }
        return $"{d:F1} {u[i]}";
    }

    private void StartBtn_Click(object sender, RoutedEventArgs e)
    {
        Confirmed = true;
        DialogResult = true;
        Close();
    }

    private void CancelBtn_Click(object sender, RoutedEventArgs e)
    {
        Confirmed = false;
        DialogResult = false;
        Close();
    }
}
