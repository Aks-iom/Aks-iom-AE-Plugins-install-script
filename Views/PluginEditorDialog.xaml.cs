using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows;
using AEPluginInstaller.Models;
using AEPluginInstaller.Services.Localization;
using Button = System.Windows.Controls.Button;

namespace AEPluginInstaller.Views;

/// <summary>
/// Лёгкая обёртка над <see cref="EditableFileRow"/>, добавляющая нумерованный заголовок
/// карточки («Файл #1»). Нужна только в этом диалоге — модель файла не трогаем.
/// </summary>
public class DialogFileRow : INotifyPropertyChanged
{
    public EditableFileRow Inner { get; }

    public DialogFileRow(EditableFileRow inner) { Inner = inner; }

    public string GoogleDriveUrl
    {
        get => Inner.GoogleDriveUrl;
        set { Inner.GoogleDriveUrl = value; Notify(); }
    }
    public string FileName
    {
        get => Inner.FileName;
        set { Inner.FileName = value; Notify(); }
    }
    public PluginType Type
    {
        get => Inner.Type;
        set { Inner.Type = value; Notify(); }
    }
    public string TargetPath
    {
        get => Inner.TargetPath;
        set { Inner.TargetPath = value; Notify(); }
    }

    private string _headerText = "";
    public string HeaderText
    {
        get => _headerText;
        set { _headerText = value; Notify(); }
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    private void Notify([CallerMemberName] string? n = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
}

public partial class PluginEditorDialog : Window
{
    private readonly EditablePluginRow _row;
    private readonly ObservableCollection<DialogFileRow> _files = new();

    public PluginEditorDialog(EditablePluginRow row)
    {
        InitializeComponent();
        Helpers.DarkTitleBar.Apply(this);

        _row = row;
        NameBox.Text = row.Name;

        foreach (var f in row.Files)
            _files.Add(new DialogFileRow(f));

        FilesList.ItemsSource = _files;
        RefreshHeaders();
    }

    private void RefreshHeaders()
    {
        for (int i = 0; i < _files.Count; i++)
            _files[i].HeaderText = L10n.T("pluged.file_header", i + 1);
        FilesCountText.Text = L10n.T("ed.files_count", _files.Count);
    }

    private void AddFileBtn_Click(object sender, RoutedEventArgs e)
    {
        _files.Add(new DialogFileRow(new EditableFileRow(new PluginFile { Type = PluginType.Plugin })));
        RefreshHeaders();
    }

    private void RemoveFileBtn_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is DialogFileRow row)
        {
            _files.Remove(row);
            RefreshHeaders();
        }
    }

    private void SaveBtn_Click(object sender, RoutedEventArgs e)
    {
        // Применяем изменения в исходный EditablePluginRow.
        _row.Name = string.IsNullOrWhiteSpace(NameBox.Text) ? "—" : NameBox.Text.Trim();
        _row.Files.Clear();
        foreach (var f in _files)
            _row.Files.Add(f.Inner);

        DialogResult = true;
        Close();
    }

    private void CancelBtn_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }
}
