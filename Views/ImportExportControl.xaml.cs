using System;
using System.Windows;
using System.Windows.Controls;

namespace AEPluginInstaller.Views;

public partial class ImportExportControl : System.Windows.Controls.UserControl
{
    public event Action? OnImport;
    public event Action? OnExport;

    public ImportExportControl(bool hasConfig)
    {
        InitializeComponent();
        ExportBtn.IsEnabled = hasConfig;
    }

    private void ImportBtn_Click(object sender, RoutedEventArgs e)
    {
        OnImport?.Invoke();
    }

    private void ExportBtn_Click(object sender, RoutedEventArgs e)
    {
        OnExport?.Invoke();
    }
}
