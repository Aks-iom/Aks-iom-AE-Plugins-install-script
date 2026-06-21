using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;

namespace AEPluginInstaller.Services.Install.Steps;

/// <summary>
/// JSON: <c>{"type":"copy_file","source":"{SRC_DIR}/X.aex","target":"{PLUGINS_DIR}"}</c>.
/// Если target — папка, файл копируется внутрь с именем из source.
/// </summary>
public class CopyFileStep : IInstallStep
{
    public string Source { get; init; } = "";
    public string Target { get; init; } = "";

    public StepResult Execute(InstallContext ctx)
    {
        var arts = new List<Artifact>();
        try
        {
            var src = ctx.Expand(Source);
            var dst = ctx.Expand(Target);
            if (!File.Exists(src))
                return StepResult.Fail($"copy_file: source not found: {src}", arts);

            string finalPath, dstDir;
            // Целью считаем папку, если: путь оканчивается на разделитель,
            // папка уже существует, ИЛИ листовое имя не выглядит как файл
            // (у источника есть расширение, а у цели — нет). Это спасает рецепты вида
            // "{PLUGINS_DIR}/VideoCopilot": папка может не существовать на первой
            // установке, но смысл всё равно — «положить файл внутрь VideoCopilot/»,
            // а не «создать файл VideoCopilot без расширения и перетирать его каждым плагином».
            var explicitDir = dst.EndsWith('/') || dst.EndsWith('\\') || Directory.Exists(dst);
            var heuristicDir = !explicitDir && Path.HasExtension(src) && !Path.HasExtension(dst);
            bool targetIsDirectory = explicitDir || heuristicDir;

            if (targetIsDirectory)
            {
                dstDir = dst;
                finalPath = Path.Combine(dstDir, Path.GetFileName(src));
                if (heuristicDir)
                    ctx.LogDebug($"copy_file: target '{dst}' трактуется как папка (нет расширения, source имеет .{Path.GetExtension(src).TrimStart('.')}). Файл → {finalPath}");
            }
            else
            {
                dstDir = Path.GetDirectoryName(dst) ?? "";
                finalPath = dst;
            }

            var dirWasMissing = !string.IsNullOrEmpty(dstDir) && !Directory.Exists(dstDir);
            if (!string.IsNullOrEmpty(dstDir))
            {
                // Создаём всю иерархию папок, даже если несколько уровней отсутствуют.
                // Если родителя не было — сообщаем пользователю явно, иначе по логу
                // нельзя понять, попали ли файлы в реальную папку плагинов AE.
                Directory.CreateDirectory(dstDir);
                if (dirWasMissing)
                {
                    arts.Add(Artifact.Dir(dstDir));
                    ctx.LogWarn($"Целевая папка не существовала, создана: {dstDir}");
                    ctx.LogWarn("Если плагин не появится в After Effects — проверьте, что AE действительно установлен по этому пути.");
                }
            }

            File.Copy(src, finalPath, overwrite: true);
            arts.Add(Artifact.File(finalPath));

            // Пост-проверка: убеждаемся, что файл реально на месте и не нулевого размера
            // (защита от тех самых «лог успех, но файла нет» сценариев).
            var fi = new FileInfo(finalPath);
            if (!fi.Exists)
                return StepResult.Fail($"copy_file: File.Copy не выбросил ошибку, но файл отсутствует: {finalPath}", arts);
            var srcLen = new FileInfo(src).Length;
            if (fi.Length != srcLen)
                return StepResult.Fail(
                    $"copy_file: размер скопированного файла {fi.Length} != source {srcLen} ({finalPath})", arts);

            ctx.Log($"   ✓ Скопирован файл → {finalPath}");
            return StepResult.Ok(arts);
        }
        catch (Exception ex)
        {
            return StepResult.Fail($"copy_file failed: {ex.Message}", arts);
        }
    }

    public class Factory : IInstallStepFactory
    {
        public string TypeName => "copy_file";
        public IInstallStep Create(JsonElement node) => new CopyFileStep
        {
            Source = node.GetProperty("source").GetString() ?? "",
            Target = node.GetProperty("target").GetString() ?? ""
        };
    }
}
