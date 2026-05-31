using System.Windows;
using System.Windows.Controls;
using Button = System.Windows.Controls.Button;

namespace AEPluginInstaller.Views;

public enum AppDialogIcon { None, Info, Question, Warning, Error, Success }
public enum AppDialogButtons { Ok, OkCancel, YesNo, YesNoCancel }
public enum AppDialogResult { None, Ok, Yes, No, Cancel }

public partial class AppMessageDialog : Window
{
    public AppDialogResult Result { get; private set; } = AppDialogResult.None;

    private AppMessageDialog(string title, string message, AppDialogIcon icon, AppDialogButtons buttons)
    {
        InitializeComponent();
        AEPluginInstaller.Helpers.DarkTitleBar.Apply(this);
        TitleText.Text = title;
        MessageText.Text = message;

        IconText.Text = icon switch
        {
            AppDialogIcon.Info     => "ℹ",
            AppDialogIcon.Question => "?",
            AppDialogIcon.Warning  => "⚠",
            AppDialogIcon.Error    => "✖",
            AppDialogIcon.Success  => "✓",
            _                      => ""
        };
        IconText.Foreground = icon switch
        {
            AppDialogIcon.Warning => (System.Windows.Media.Brush)FindResource("AccentBrush"),
            AppDialogIcon.Error   => (System.Windows.Media.Brush)FindResource("DangerBrush"),
            AppDialogIcon.Success => (System.Windows.Media.Brush)FindResource("SuccessBrush"),
            _                     => (System.Windows.Media.Brush)FindResource("AccentBrush")
        };
        if (icon == AppDialogIcon.None) IconText.Visibility = Visibility.Collapsed;

        BuildButtons(buttons);
    }

    private void BuildButtons(AppDialogButtons buttons)
    {
        ButtonsPanel.Children.Clear();
        switch (buttons)
        {
            case AppDialogButtons.Ok:
                Add("OK", AppDialogResult.Ok, primary: true);
                break;
            case AppDialogButtons.OkCancel:
                Add("Отмена", AppDialogResult.Cancel);
                Add("OK", AppDialogResult.Ok, primary: true);
                break;
            case AppDialogButtons.YesNo:
                Add("Нет", AppDialogResult.No);
                Add("Да", AppDialogResult.Yes, primary: true);
                break;
            case AppDialogButtons.YesNoCancel:
                Add("Отмена", AppDialogResult.Cancel);
                Add("Нет", AppDialogResult.No);
                Add("Да", AppDialogResult.Yes, primary: true);
                break;
        }
    }

    private void Add(string text, AppDialogResult result, bool primary = false)
    {
        var btn = new Button
        {
            Content = text,
            Padding = new Thickness(18, 8, 18, 8),
            Margin = new Thickness(8, 0, 0, 0),
            Style = (Style)FindResource(primary ? "PrimaryButton" : "GhostButton"),
            MinWidth = 80
        };
        btn.Click += (_, _) =>
        {
            Result = result;
            DialogResult = result is AppDialogResult.Ok or AppDialogResult.Yes;
            Close();
        };
        ButtonsPanel.Children.Add(btn);
    }

    // ===================== Статические шорткаты =====================

    public static AppDialogResult Show(Window? owner, string title, string message,
        AppDialogIcon icon = AppDialogIcon.Info,
        AppDialogButtons buttons = AppDialogButtons.Ok)
    {
        var dlg = new AppMessageDialog(title, message, icon, buttons);
        if (owner != null) dlg.Owner = owner;
        dlg.ShowDialog();
        return dlg.Result;
    }

    public static void Info(Window? owner, string title, string message)
        => Show(owner, title, message, AppDialogIcon.Info, AppDialogButtons.Ok);

    public static void Warn(Window? owner, string title, string message)
        => Show(owner, title, message, AppDialogIcon.Warning, AppDialogButtons.Ok);

    public static bool Confirm(Window? owner, string title, string message)
        => Show(owner, title, message, AppDialogIcon.Question, AppDialogButtons.YesNo)
            == AppDialogResult.Yes;
}
