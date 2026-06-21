using System.IO;
using System.Windows;

namespace AEPluginInstaller.Views;

public partial class AeNotFoundDialog : Window
{
    /// <summary>Выбранный пользователем путь к папке AE. null = пользователь отменил.</summary>
    public string? SelectedPath { get; private set; }

    public AeNotFoundDialog(string version)
    {
        InitializeComponent();
        AEPluginInstaller.Helpers.DarkTitleBar.Apply(this);
        Title = AEPluginInstaller.Services.Localization.L10n.T("dlg.ae_not_found.title", version);
        TitleText.Text = Title;
        SubtitleText.Text = AEPluginInstaller.Services.Localization.L10n.T("dlg.ae_not_found.subtitle", version);
    }

    private void BrowseBtn_Click(object sender, RoutedEventArgs e)
    {
        using var dlg = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = AEPluginInstaller.Services.Localization.L10n.T("dlg.ae_not_found.browse_desc"),
            UseDescriptionForTitle = true,
            ShowNewFolderButton = false
        };
        if (dlg.ShowDialog() != System.Windows.Forms.DialogResult.OK) return;

        var folder = dlg.SelectedPath;
        if (!Directory.Exists(Path.Combine(folder, "Support Files")))
        {
            AppMessageDialog.Warn(this,
                AEPluginInstaller.Services.Localization.L10n.T("dlg.bad_path.title"),
                AEPluginInstaller.Services.Localization.L10n.T("dlg.bad_path.text", folder));
            return;
        }

        SelectedPath = folder;
        DialogResult = true;
        Close();
    }

    private void CancelBtn_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }
}
