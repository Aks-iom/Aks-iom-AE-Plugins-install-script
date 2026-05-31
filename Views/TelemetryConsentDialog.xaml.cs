using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Input;
using System.Windows.Navigation;
using AEPluginInstaller.Services.Localization;

namespace AEPluginInstaller.Views;

public partial class TelemetryConsentDialog : Window
{
    public bool IsConsentGiven { get; private set; }

    /// <summary>Указанный пользователем путь к корню After Effects (с подпапкой Support Files).
    /// Пусто, если пользователь оставил поле пустым.</summary>
    public string SelectedAePath { get; private set; } = "";

    public TelemetryConsentDialog()
    {
        InitializeComponent();
    }

    private void DragWindow(object sender, MouseButtonEventArgs e)
    {
        if (e.ChangedButton == MouseButton.Left)
            DragMove();
    }

    private void BrowseAePath_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = L10n.T("tcd.ae_path.hint"),
            UseDescriptionForTitle = true,
            ShowNewFolderButton = false
        };
        if (dlg.ShowDialog() == System.Windows.Forms.DialogResult.OK)
            AePathBox.Text = dlg.SelectedPath;
    }

    private void Continue_Click(object sender, RoutedEventArgs e)
    {
        var rawPath = AePathBox.Text?.Trim() ?? "";

        if (!string.IsNullOrEmpty(rawPath))
        {
            // Принимаем только корень установки — папку с «Support Files» внутри.
            if (!Directory.Exists(Path.Combine(rawPath, "Support Files")))
            {
                AppMessageDialog.Warn(this, L10n.T("tcd.ae_path.title"),
                    L10n.T("tcd.ae_path.bad_folder"));
                return;
            }
            SelectedAePath = rawPath;
        }

        IsConsentGiven = CbConsent.IsChecked == true;
        DialogResult = true;
        Close();
    }

    private void Hyperlink_RequestNavigate(object sender, RequestNavigateEventArgs e)
    {
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = e.Uri.AbsoluteUri,
                UseShellExecute = true
            });
            e.Handled = true;
        }
        catch { }
    }
}
