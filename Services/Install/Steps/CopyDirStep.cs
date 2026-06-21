using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;

namespace AEPluginInstaller.Services.Install.Steps;

/// <summary>
/// JSON: <c>{"type":"copy_dir","source":"...","target":"...","mode":"merge|replace"}</c>.
/// В replace-режиме делает бэкап существующей папки и регистрирует его в транзакции
/// (так что бэкап удалится только при общем commit, а при rollback — восстановится).
/// </summary>
public class CopyDirStep : IInstallStep
{
    public string Source { get; init; } = "";
    public string Target { get; init; } = "";
    public string Mode { get; init; } = "merge";  // merge | replace

    public StepResult Execute(InstallContext ctx)
    {
        var arts = new List<Artifact>();
        string? backupDir = null;
        var dst = "";
        try
        {
            var src = ctx.Expand(Source);
            dst = ctx.Expand(Target);
            if (!Directory.Exists(src))
                return StepResult.Fail($"copy_dir: source not found: {src}", arts);

            var targetExisted = Directory.Exists(dst);

            // Если родителя цели нет — это означает, что мы будем создавать всю
            // иерархию (например, .../Common/Plug-ins/7.0/MediaCore/Twixtor8AE)
            // с нуля. Это валидный сценарий, но также частый признак того, что
            // AE / Adobe Common Files на самом деле живут не там, где мы ожидаем.
            // Пишем предупреждение в UI, чтобы установка не выглядела «успешной»,
            // когда плагин фактически попал в неработающее место.
            var parent = Path.GetDirectoryName(dst);
            var parentWasMissing = !string.IsNullOrEmpty(parent) && !Directory.Exists(parent);

            if (Mode == "replace" && targetExisted)
            {
                backupDir = dst + ".aeinst_bak";
                if (Directory.Exists(backupDir))
                {
                    try { Directory.Delete(backupDir, recursive: true); } catch { }
                }
                try
                {
                    Directory.Move(dst, backupDir);
                }
                catch (Exception ex)
                {
                    return StepResult.Fail($"copy_dir(replace): cannot backup target: {ex.Message}", arts);
                }
                targetExisted = false;

                // Регистрируем бэкап в транзакции, если она доступна
                if (ctx.Transaction != null)
                {
                    ctx.Transaction.RegisterBackup(dst, backupDir);
                    backupDir = null; // под контролем транзакции
                }
            }

            if (!targetExisted)
            {
                // CopyTreeAtomic вызывает Directory.CreateDirectory(dst), что создаст
                // всю недостающую иерархию родителей — это и нужно, когда у юзера
                // ещё нет, например, .../Common/Plug-ins/7.0/MediaCore.
                CopyTreeAtomic(src, dst);
                arts.Add(Artifact.Dir(dst));
                if (parentWasMissing && !string.IsNullOrEmpty(parent))
                {
                    ctx.LogWarn($"Родительская папка не существовала, создана: {parent}");
                    ctx.LogWarn("Если плагин не появится в After Effects — проверьте, что Adobe / AE действительно установлен по этому пути.");
                }
            }
            else
            {
                // merge: пробегаем дерево, копируем недостающее
                foreach (var dir in Directory.EnumerateDirectories(src, "*", SearchOption.AllDirectories))
                {
                    var rel = Path.GetRelativePath(src, dir);
                    var dstSub = Path.Combine(dst, rel);
                    if (!Directory.Exists(dstSub))
                    {
                        Directory.CreateDirectory(dstSub);
                        arts.Add(Artifact.Dir(dstSub));
                    }
                }
                foreach (var file in Directory.EnumerateFiles(src, "*", SearchOption.AllDirectories))
                {
                    var rel = Path.GetRelativePath(src, file);
                    var dstFile = Path.Combine(dst, rel);
                    Directory.CreateDirectory(Path.GetDirectoryName(dstFile)!);
                    if (!File.Exists(dstFile))
                    {
                        File.Copy(file, dstFile);
                        arts.Add(Artifact.File(dstFile));
                    }
                }
            }

            // Если бэкап остался без транзакции — удаляем здесь
            if (backupDir != null && Directory.Exists(backupDir))
                try { Directory.Delete(backupDir, recursive: true); } catch { }

            ctx.Log($"   ✓ Скопирована папка → {dst}");
            return StepResult.Ok(arts);
        }
        catch (Exception ex)
        {
            // Восстанавливаем бэкап, если он ещё под нашим контролем
            if (backupDir != null && Directory.Exists(backupDir))
            {
                try
                {
                    if (Directory.Exists(dst)) Directory.Delete(dst, recursive: true);
                    Directory.Move(backupDir, dst);
                    ctx.Log($"   ↶ Восстановлен target из бэкапа: {dst}");
                }
                catch { }
            }
            return StepResult.Fail($"copy_dir failed: {ex.Message}", arts);
        }
    }

    private static void CopyTreeAtomic(string src, string dst)
    {
        Directory.CreateDirectory(dst);
        foreach (var dir in Directory.EnumerateDirectories(src, "*", SearchOption.AllDirectories))
            Directory.CreateDirectory(Path.Combine(dst, Path.GetRelativePath(src, dir)));
        foreach (var file in Directory.EnumerateFiles(src, "*", SearchOption.AllDirectories))
        {
            var rel = Path.GetRelativePath(src, file);
            File.Copy(file, Path.Combine(dst, rel), overwrite: true);
        }
    }

    public class Factory : IInstallStepFactory
    {
        public string TypeName => "copy_dir";
        public IInstallStep Create(JsonElement node) => new CopyDirStep
        {
            Source = node.GetProperty("source").GetString() ?? "",
            Target = node.GetProperty("target").GetString() ?? "",
            Mode = node.TryGetProperty("mode", out var m) ? m.GetString() ?? "merge" : "merge"
        };
    }
}
