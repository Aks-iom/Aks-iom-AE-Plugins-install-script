using System.Windows;

namespace AEPluginInstaller.Views;

public enum AeRunningResult { Cancel, Continue, Skip }

public partial class AeRunningDialog : Window
{
    public AeRunningResult Result { get; private set; } = AeRunningResult.Cancel;

    public AeRunningDialog()
    {
        InitializeComponent();
        AEPluginInstaller.Helpers.DarkTitleBar.Apply(this);
    }

    private void ContinueBtn_Click(object sender, RoutedEventArgs e)
    {
        // Перепроверяем — может быть пользователь уже закрыл AE
        if (Services.AeProcessChecker.IsAeRunning())
        {
            // Подсвечиваем что всё ещё запущен
            Title = Services.Localization.L10n.T("dlg.ae_running.title") + " ⚠";
            return;
        }
        Result = AeRunningResult.Continue;
        DialogResult = true;
        Close();
    }

    private void SkipBtn_Click(object sender, RoutedEventArgs e)
    {
        Result = AeRunningResult.Skip;
        DialogResult = true;
        Close();
    }

    private void CancelBtn_Click(object sender, RoutedEventArgs e)
    {
        Result = AeRunningResult.Cancel;
        DialogResult = false;
        Close();
    }
}
