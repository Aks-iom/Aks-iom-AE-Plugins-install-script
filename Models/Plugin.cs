using System.Collections.Generic;

namespace AEPluginInstaller.Models;

public enum PluginType
{
    Auto,        // определяется по расширению
    Plugin,      // .aex
    Script,      // .jsx / .jsxbin
    ScriptUI,    // в ScriptUI Panels
    Preset,      // .ffx
    Archive,     // .zip / .rar / .7z — распаковать и разложить
    Installer,   // .exe — запустить как инсталлер
    RegFile      // .reg — импортировать в реестр
}

/// <summary>
/// Один скачиваемый файл, привязанный к плагину.
/// Используется, когда плагин состоит из нескольких частей (например .exe + .aex + .reg).
/// </summary>
public class PluginFile
{
    public string GoogleDriveUrl { get; set; } = "";
    public string FileName { get; set; } = "";       // желаемое имя (опц.) — например "Optical_Flares.aex"
    public PluginType Type { get; set; } = PluginType.Auto;
    /// <summary>Абсолютный путь куда положить (или с подстановками {plugins}/{scripts}/...).</summary>
    public string TargetPath { get; set; } = "";
    /// <summary>Ожидаемая контрольная сумма. Поддерживается md5/sha1/sha256 (по длине).</summary>
    public string Hash { get; set; } = "";
}

public class Plugin
{
    public string Name { get; set; } = "";

    /// <summary>Простой случай — один файл по ссылке. Если используется Files — это поле игнорируется.</summary>
    public string GoogleDriveUrl { get; set; } = "";
    public PluginType Type { get; set; } = PluginType.Auto;
    /// <summary>Опциональный override целевой папки. Если пусто — определяется по типу.</summary>
    public string CustomTargetFolder { get; set; } = "";

    /// <summary>
    /// Для плагинов-инсталляторов из базового каталога (поле <c>bat_path</c>):
    /// относительный путь ВНУТРИ скачанного архива до .exe/.bat, который нужно
    /// запустить ПОСЛЕ распаковки (например "RSMB/setup.exe", "RedGiant\\RedGiant.bat").
    /// Если задан — архив распаковывается во временную папку и запускается этот файл,
    /// а не раскладывается по Plug-ins.
    /// </summary>
    public string RunAfterExtract { get; set; } = "";

    /// <summary>Если плагин состоит из нескольких файлов — заполняется это поле.</summary>
    public List<PluginFile> Files { get; set; } = new();

    public string Description { get; set; } = "";
    public string Version { get; set; } = "";
    public string Size { get; set; } = "";
    public string Warning { get; set; } = "";

    /// <summary>Ожидаемый хеш для одиночного файла (когда Files пуст).</summary>
    public string Hash { get; set; } = "";

    /// <summary>
    /// Дополнительные подсказки для эвристики «уже установлено» —
    /// фрагменты имён файлов/папок, по которым плагин узнаётся на диске
    /// (например, "twixtor", "twixtor8ae", "uwu2x-pro").
    /// </summary>
    public List<string> Keywords { get; set; } = new();
}

public class PluginConfig
{
    public string Name { get; set; } = "Новый конфиг";
    public string Description { get; set; } = "";
    public List<Plugin> Plugins { get; set; } = new();
}

