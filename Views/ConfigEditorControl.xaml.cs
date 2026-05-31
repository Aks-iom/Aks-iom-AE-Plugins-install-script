using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Windows;
using System.Windows.Controls;
using AEPluginInstaller.Models;
using AEPluginInstaller.Services.Localization;
using Button = System.Windows.Controls.Button;

namespace AEPluginInstaller.Views;

/// <summary>Редактируемая обёртка над одним файлом плагина.</summary>
public class EditableFileRow : INotifyPropertyChanged
{
    public PluginFile Model { get; }
    public EditableFileRow(PluginFile m) { Model = m; }

    public string GoogleDriveUrl
    {
        get => Model.GoogleDriveUrl;
        set { Model.GoogleDriveUrl = value ?? ""; Notify(); }
    }
    public string FileName
    {
        get => Model.FileName;
        set { Model.FileName = value ?? ""; Notify(); }
    }
    public PluginType Type
    {
        get => Model.Type;
        set { Model.Type = value; Notify(); }
    }
    public string TargetPath
    {
        get => Model.TargetPath;
        set { Model.TargetPath = value ?? ""; Notify(); }
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    private void Notify([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

/// <summary>
/// Редактируемая обёртка над плагином. Всегда работает через <see cref="Files"/>:
/// если в исходной модели был «простой» URL — он мигрируется в один файл.
/// </summary>
public class EditablePluginRow : INotifyPropertyChanged
{
    public Plugin Model { get; }
    public ObservableCollection<EditableFileRow> Files { get; } = new();

    public EditablePluginRow(Plugin p)
    {
        Model = p;

        // Миграция: «простой» одиночный URL → один файл в списке.
        if (Model.Files.Count == 0 && !string.IsNullOrWhiteSpace(Model.GoogleDriveUrl))
        {
            Model.Files.Add(new PluginFile
            {
                GoogleDriveUrl = Model.GoogleDriveUrl,
                Type = Model.Type == PluginType.Auto ? PluginType.Archive : Model.Type,
                TargetPath = Model.CustomTargetFolder ?? ""
            });
        }

        foreach (var f in Model.Files)
            Files.Add(new EditableFileRow(f));

        Files.CollectionChanged += (_, _) =>
        {
            Notify(nameof(FilesCount));
            Notify(nameof(FilesCountText));
            Notify(nameof(TypeSummary));
        };
    }

    public string Name
    {
        get => Model.Name;
        set { Model.Name = value ?? ""; Notify(); }
    }

    public int FilesCount => Files.Count;
    public string FilesCountText => L10n.T("ed.files_count", Files.Count);

    /// <summary>
    /// Человекочитаемое описание состава плагина:
    ///  • пусто → «—»
    ///  • один файл-архив с RunAfterExtract → «Установщик»
    ///  • один файл одного типа → название этого типа
    ///  • несколько файлов одного типа → «3× Плагин»
    ///  • смешанные типы → «Архив + Скрипт» (через «+»)
    /// </summary>
    public string TypeSummary
    {
        get
        {
            if (Files.Count == 0) return "—";

            // Архив + RunAfterExtract = инсталлер.
            if (Files.Count == 1
                && Files[0].Type == PluginType.Archive
                && !string.IsNullOrWhiteSpace(Model.RunAfterExtract))
            {
                return L10n.T("ed.type.installer");
            }

            var groups = Files.GroupBy(f => f.Type).ToList();
            if (groups.Count == 1)
            {
                var t = groups[0].Key;
                var label = TypeLabel(t);
                return groups[0].Count() > 1 ? $"{groups[0].Count()}× {label}" : label;
            }

            return string.Join(" + ", groups.Select(g => TypeLabel(g.Key)));
        }
    }

    private static string TypeLabel(PluginType t) => t switch
    {
        PluginType.Plugin    => L10n.T("ed.type.plugin"),
        PluginType.Script    => L10n.T("ed.type.script"),
        PluginType.ScriptUI  => L10n.T("ed.type.scriptui"),
        PluginType.Archive   => L10n.T("ed.type.archive"),
        PluginType.Installer => L10n.T("ed.type.installer"),
        PluginType.RegFile   => L10n.T("ed.type.reg"),
        _                    => L10n.T("ed.type.plugin"),
    };

    /// <summary>Перерасчёт сводки типов после редактирования файлов в диалоге.</summary>
    public void RefreshDerived()
    {
        Notify(nameof(Name));
        Notify(nameof(FilesCount));
        Notify(nameof(FilesCountText));
        Notify(nameof(TypeSummary));
    }

    /// <summary>Возвращает модель в состоянии «готов к сериализации» — Files актуальны, top-level url чистится.</summary>
    public Plugin ToPlugin()
    {
        Model.Files = Files.Select(r => r.Model).ToList();
        // Очищаем legacy-поля одиночного файла — теперь источник истины Files.
        Model.GoogleDriveUrl = "";
        Model.Type = PluginType.Auto;
        Model.CustomTargetFolder = "";
        return Model;
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    private void Notify([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

public partial class ConfigEditorControl : System.Windows.Controls.UserControl
{
    private readonly PluginConfig _config;
    private readonly ObservableCollection<EditablePluginRow> _rows = new();

    public event Action<PluginConfig>? OnSave;
    public event Action? OnCancel;

    public ConfigEditorControl(PluginConfig config)
    {
        InitializeComponent();
        _config = config;
        NameBox.Text = config.Name;
        DescBox.Text = config.Description;
        foreach (var p in config.Plugins)
            _rows.Add(new EditablePluginRow(p));
        PluginsList.ItemsSource = _rows;
    }

    private void AddPluginBtn_Click(object sender, RoutedEventArgs e)
    {
        var p = new Plugin { Name = "Новый плагин", Type = PluginType.Auto };
        var row = new EditablePluginRow(p);
        // Сразу добавляем один пустой файл — чтобы было что заполнять.
        row.Files.Add(new EditableFileRow(new PluginFile { Type = PluginType.Plugin }));
        _rows.Add(row);

        // Сразу открываем редактор нового плагина.
        OpenEditor(row);
    }

    private void RemovePluginBtn_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is EditablePluginRow row)
            _rows.Remove(row);
    }

    private void EditPluginBtn_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is EditablePluginRow row)
            OpenEditor(row);
    }

    private void OpenEditor(EditablePluginRow row)
    {
        var owner = Window.GetWindow(this);
        var dlg = new PluginEditorDialog(row) { Owner = owner };
        if (dlg.ShowDialog() == true)
        {
            // Дочерний диалог уже применил изменения; обновляем сводку.
            row.RefreshDerived();
        }
    }

    private void SaveBtn_Click(object sender, RoutedEventArgs e)
    {
        _config.Name = string.IsNullOrWhiteSpace(NameBox.Text) ? "Конфиг" : NameBox.Text.Trim();
        _config.Description = DescBox.Text ?? "";
        _config.Plugins = _rows.Select(r => r.ToPlugin()).ToList();

        OnSave?.Invoke(_config);
    }

    private void CancelBtn_Click(object sender, RoutedEventArgs e)
    {
        OnCancel?.Invoke();
    }
}
