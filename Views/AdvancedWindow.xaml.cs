using System.Windows;
using AEPluginInstaller.Models;
using AEPluginInstaller.Services.Localization;

namespace AEPluginInstaller.Views;

public partial class AdvancedWindow : Window
{
    private readonly MainWindow _mainWnd;

    public AdvancedWindow(MainWindow mainWnd, bool hasConfig)
    {
        InitializeComponent();
        Helpers.DarkTitleBar.Apply(this);
        _mainWnd = mainWnd;

        EditBtn.IsEnabled = hasConfig;
        DeleteBtn.IsEnabled = hasConfig;
    }

    private void MinBtn_Click(object sender, RoutedEventArgs e)
        => WindowState = WindowState.Minimized;

    private void CloseBtn_Click(object sender, RoutedEventArgs e)
        => Close();

    private void ClearHost()
    {
        Host.Content = null;
        PlaceholderText.Visibility = Visibility.Visible;
    }

    private void SetHostContent(object content)
    {
        Host.Content = content;
        PlaceholderText.Visibility = Visibility.Collapsed;
    }

    private void NavSettings_Click(object sender, RoutedEventArgs e)
    {
        var settingsCtrl = new SettingsControl();
        settingsCtrl.OnBlacklistChanged += () => _mainWnd.NotifyBlacklistChanged();
        settingsCtrl.OnAePathsChanged += () => _mainWnd.NotifyBlacklistChanged();
        SetHostContent(settingsCtrl);
    }

    private void NavNewConfig_Click(object sender, RoutedEventArgs e)
    {
        var cfg = new PluginConfig { Name = _mainWnd.GetNewConfigName() };
        var editor = new ConfigEditorControl(cfg);
        
        editor.OnSave += (savedCfg) =>
        {
            _mainWnd.AddConfigAndSelect(savedCfg);
            ClearHost();
            EditBtn.IsEnabled = true;
            DeleteBtn.IsEnabled = true;
        };
        editor.OnCancel += ClearHost;
        
        SetHostContent(editor);
    }

    private void NavEditConfig_Click(object sender, RoutedEventArgs e)
    {
        if (_mainWnd.CurrentConfig == null) return;
        var cfg = _mainWnd.CurrentConfig;
        var oldName = cfg.Name;
        
        var editor = new ConfigEditorControl(cfg);
        editor.OnSave += (savedCfg) =>
        {
            _mainWnd.UpdateExistingConfig(savedCfg, oldName);
            ClearHost();
        };
        editor.OnCancel += ClearHost;
        
        SetHostContent(editor);
    }

    private void NavDeleteConfig_Click(object sender, RoutedEventArgs e)
    {
        _mainWnd.DeleteConfigBtn_Click(sender, e);
        if (_mainWnd.CurrentConfig == null)
        {
            EditBtn.IsEnabled = false;
            DeleteBtn.IsEnabled = false;
            ClearHost();
        }
    }

    private void NavImportExport_Click(object sender, RoutedEventArgs e)
    {
        var control = new ImportExportControl(_mainWnd.CurrentConfig != null);
        control.OnImport += () =>
        {
            _mainWnd.ImportConfigBtn_Click(sender, e);
            if (_mainWnd.CurrentConfig != null)
            {
                EditBtn.IsEnabled = true;
                DeleteBtn.IsEnabled = true;
            }
        };
        control.OnExport += () =>
        {
            _mainWnd.ExportConfigBtn_Click(sender, e);
        };
        SetHostContent(control);
    }
}
