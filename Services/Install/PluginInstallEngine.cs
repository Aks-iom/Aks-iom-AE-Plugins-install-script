using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text.Json;
using AEPluginInstaller.Services.Install.Steps;

namespace AEPluginInstaller.Services.Install;

/// <summary>
/// Выполняет install_steps в транзакции, при успехе записывает манифест.
/// </summary>
public class PluginInstallEngine
{
    private readonly string _installedDir;

    public PluginInstallEngine(string installedDir)
    {
        _installedDir = installedDir;
        System.IO.Directory.CreateDirectory(_installedDir);
    }

    /// <summary>
    /// Выполняет шаги из <paramref name="stepsJson"/> (массив объектов).
    /// При любой ошибке шага — откатывает уже выполненные.
    /// </summary>
    public bool Install(string stepsJson, InstallContext ctx, string pluginVersion = "")
    {
        var pluginSw = Stopwatch.StartNew();
        ctx.LogDebug($"plugin={ctx.PluginName} version={(string.IsNullOrEmpty(pluginVersion) ? "?" : pluginVersion)} ae={ctx.AeVersion}");
        ctx.LogDebug($"src_dir={ctx.SrcDir}");
        if (ctx.Paths.TryGetValue("PLUGINS_DIR", out var pd)) ctx.LogDebug($"plugins_dir={pd}");
        if (ctx.Paths.TryGetValue("SCRIPTS_DIR", out var sd)) ctx.LogDebug($"scripts_dir={sd}");
        if (ctx.Paths.TryGetValue("PRESETS_DIR", out var rd)) ctx.LogDebug($"presets_dir={rd}");
        if (!string.IsNullOrEmpty(ctx.CustomPath)) ctx.LogDebug($"custom_path={ctx.CustomPath}");

        if (string.IsNullOrWhiteSpace(stepsJson))
        {
            ctx.LogWarn($"У плагина {ctx.PluginName} нет install_steps — пропуск.");
            return false;
        }

        List<IInstallStep> steps;
        try
        {
            using var doc = JsonDocument.Parse(stepsJson);
            steps = StepBuilder.BuildSteps(doc.RootElement);
        }
        catch (StepParseException ex)
        {
            ctx.LogError($"Ошибка парсинга install_steps {ctx.PluginName}: {ex.Message}");
            return false;
        }
        catch (JsonException ex)
        {
            ctx.LogError($"Невалидный JSON install_steps {ctx.PluginName}: {ex.Message}");
            return false;
        }

        if (steps.Count == 0)
        {
            ctx.LogWarn($"У плагина {ctx.PluginName} список шагов пуст.");
            return false;
        }

        using var tx = new InstallTransaction(ctx);
        ctx.Transaction = tx;
        try
        {
            for (int i = 0; i < steps.Count; i++)
            {
                if (ctx.Cancel.IsCancellationRequested)
                {
                    ctx.LogWarn($"Установка {ctx.PluginName} отменена пользователем перед шагом {i + 1}.");
                    return false;
                }

                var step = steps[i];
                var stepName = step.GetType().Name.Replace("Step", "");
                ctx.Log($"   ── шаг {i + 1}/{steps.Count}: {stepName}");

                var stepSw = Stopwatch.StartNew();
                StepResult r;
                try
                {
                    r = step.Execute(ctx);
                }
                catch (Exception ex)
                {
                    stepSw.Stop();
                    ctx.LogError($"Шаг {stepName} бросил исключение через {stepSw.Elapsed.TotalSeconds:0.000}s:");
                    ctx.LogError($"{ex.GetType().FullName}: {ex.Message}");
                    if (!string.IsNullOrEmpty(ex.StackTrace))
                        ctx.LogError(ex.StackTrace);
                    return false;
                }
                stepSw.Stop();

                tx.AddArtifacts(r.Artifacts);
                if (!r.Success)
                {
                    ctx.LogError($"Шаг {stepName} провален через {stepSw.Elapsed.TotalSeconds:0.000}s: {r.Error}");
                    return false;
                }
                ctx.LogDebug($"шаг {stepName} ok за {stepSw.Elapsed.TotalSeconds:0.000}s (artifacts: {r.Artifacts.Count})");
            }
            tx.Commit();
        }
        finally
        {
            ctx.Transaction = null;
        }

        try
        {
            InstalledManifest.Write(
                _installedDir, ctx.PluginName, ctx.AeVersion,
                pluginVersion, new List<Artifact>(tx.Artifacts));
            ctx.LogDebug($"манифест записан: {_installedDir}");
        }
        catch (Exception ex)
        {
            ctx.LogWarn($"Установка прошла, но не удалось записать манифест: {ex.Message}");
            // не считаем это ошибкой установки — файлы уже на местах
        }

        pluginSw.Stop();
        ctx.LogDebug($"plugin '{ctx.PluginName}' installed in {pluginSw.Elapsed.TotalSeconds:0.000}s");
        return true;
    }

}
