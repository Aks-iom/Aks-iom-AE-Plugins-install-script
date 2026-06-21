using System.Diagnostics;
using System.Windows;
using System.Windows.Navigation;

namespace AEPluginInstaller.Views;

public partial class InstallCompleteDialog : Window
{
    public InstallCompleteDialog(int ok, int fail)
    {
        InitializeComponent();
        Helpers.DarkTitleBar.Apply(this);

        OkCountText.Text = ok.ToString();
        FailCountText.Text = fail.ToString();

        if (fail > 0)
        {
            IconText.Text = "⚠";
            IconText.Foreground = (System.Windows.Media.Brush)FindResource("DangerBrush");
            HintText.Visibility = Visibility.Visible;
        }
    }

    private void Link_RequestNavigate(object sender, RequestNavigateEventArgs e)
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
        catch { /* ignore */ }
    }

    private void CloseBtn_Click(object sender, RoutedEventArgs e) => Close();
}
