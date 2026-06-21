using System.Collections.Generic;
using System.Text.Json;

namespace AEPluginInstaller.Services.Install;

/// <summary>
/// Встроенные «рецепты» установки для плагинов из папки <c>other</c>,
/// перенесённые из их .bat-файлов прямо в код.
///
/// Каждый рецепт описывается обычными install_steps — точно теми же,
/// что движок умеет выполнять (copy_file / copy_dir / extract_zip /
/// import_reg / set_reg_value / enable_cep_debug / run_exe).
///
/// Этапы для одного плагина (например, «положить .aex», «положить лицензию»,
/// «скопировать ассеты», «прописать ключи реестра») — это отдельные шаги,
/// которые при установке выполняются по порядку как одна транзакция.
/// </summary>
public static class BuiltInRecipes
{
    /// <summary>
    /// Возвращает JSON-массив install_steps для плагина по его имени
    /// (как оно записано в plugins.json), либо <c>null</c>, если рецепта нет
    /// и плагин нужно ставить старым путём (распаковать архив + запустить bat).
    /// </summary>
    /// <param name="pluginName">Имя плагина из каталога.</param>
    /// <param name="archiveSrc">Источник скачанного архива в формате install_steps,
    /// например <c>{SRC_DIR}/archive_0.zip</c>.</param>
    /// <param name="rootInArchive">Имя корневой папки внутри архива
    /// (первая часть bat_path до разделителя), например <c>Bokeh</c>.</param>
    public static string? TryBuildStepsJson(string pluginName, string archiveSrc, string rootInArchive)
    {
        var steps = Build(pluginName, archiveSrc, rootInArchive);
        return steps == null ? null : JsonSerializer.Serialize(steps);
    }

    /// <summary>Доступен ли встроенный рецепт для данного имени плагина.</summary>
    public static bool Has(string pluginName) =>
        Build(pluginName, "{SRC_DIR}/dummy.zip", pluginName) != null;

    private static List<object>? Build(string name, string archiveSrc, string root)
    {
        // STAGE = временная папка, куда распаковывается архив
        const string stage = "{SRC_DIR}/_pkg";
        // PKG = корневая папка плагина внутри распакованного архива
        var pkg = $"{stage}/{root}";

        return name switch
        {
            // Просто .aex в Plugins Everything
            "Bokeh" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyFile($"{pkg}/Bokeh.aex", "{PLUGINS_DIR}/Plugins Everything")
            },

            // .aex в общую папку MediaCore
            "Deep_Glow" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyFile($"{pkg}/Deep Glow.aex", "{COMMON_PLUGINS}")
            },

            // .aex + сопровождающая .dll в MediaCore
            "Deep_Glow2" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyFile($"{pkg}/DeepGlow2.aex", "{COMMON_PLUGINS}"),
                CopyFile($"{pkg}/IrisBlurSDK.dll", "{COMMON_PLUGINS}")
            },

            // Element 3D: плагин + лицензия + ассеты в Documents.
            // У файла лицензии нет расширения — добавляем явный слэш у target,
            // иначе CopyFileStep не сможет определить, что это папка.
            "Element" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyFile($"{pkg}/Element.aex", "{PLUGINS_DIR}/VideoCopilot/"),
                CopyFile($"{pkg}/element2_license", "{PROGRAMDATA}/VideoCopilot/"),
                CopyDir($"{pkg}/VideoCopilot", "{USER_DOCS}/VideoCopilot", "merge")
            },

            // Скрипт ScriptUI Panels
            "Fast_Layers" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyFile($"{pkg}/Fast_Layers.jsx", "{SCRIPTS_DIR}")
            },

            // CEP-расширение Flow + ключи реестра PlayerDebugMode
            "Flow" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyDir($"{pkg}/flow-v1.5.2", "{CEP_EXTENSIONS}/flow", "replace"),
                EnableCepDebug()
            },

            // .aex в VideoCopilot
            "Fxconsole" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyFile($"{pkg}/FXConsole.aex", "{PLUGINS_DIR}/VideoCopilot")
            },

            "Glitchify" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyFile($"{pkg}/Glitchify.aex", "{PLUGINS_DIR}/VideoCopilot")
            },

            // .zxp = zip — распаковываем сразу в CEP\extensions\com.PrimeTools
            "Prime_tool" => new List<object>
            {
                Extract(archiveSrc, stage),
                Extract($"{pkg}/com.PrimeTools.cep.zxp", "{CEP_EXTENSIONS}/com.PrimeTools")
            },

            "Saber" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyFile($"{pkg}/Saber.aex", "{PLUGINS_DIR}/VideoCopilot")
            },

            "Shake_Generator" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyFile($"{pkg}/Shake_Generator.jsx", "{SCRIPTS_DIR}")
            },

            "Textevo2" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyFile($"{pkg}/textevo2.jsxbin", "{SCRIPTS_DIR}")
            },

            // Twitch: плагин + key-файл
            "Twich" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyFile($"{pkg}/twitch.aex", "{PLUGINS_DIR}/VideoCopilot"),
                CopyFile($"{pkg}/twitch_ae.key", "{PLUGINS_DIR}/VideoCopilot")
            },

            // Twixtor — целая папка Twixtor8AE в MediaCore
            "Twixtor" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyDir($"{pkg}/Twixtor8AE", "{COMMON_PLUGINS}/Twixtor8AE", "merge")
            },

            // uwu2x: CEP-расширение + ключи реестра
            "Uwu2x" => new List<object>
            {
                Extract(archiveSrc, stage),
                CopyDir($"{pkg}/uwu2x", "{CEP_EXTENSIONS}/uwu2x", "replace"),
                EnableCepDebug()
            },

            _ => null
        };
    }

    // ── helpers ──────────────────────────────────────────────────────────

    private static object Extract(string source, string target) =>
        new { type = "extract_zip", source, target };

    private static object CopyFile(string source, string target) =>
        new { type = "copy_file", source, target };

    private static object CopyDir(string source, string target, string mode) =>
        new { type = "copy_dir", source, target, mode };

    private static object EnableCepDebug() =>
        new { type = "enable_cep_debug" };
}
