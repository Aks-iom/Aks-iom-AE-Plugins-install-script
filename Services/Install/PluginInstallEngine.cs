using System;
using System.Collections.Generic;
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
        if (string.IsNullOrWhiteSpace(stepsJson))
        {
            ctx.Log($"[!] У плагина {ctx.PluginName} нет install_steps — пропуск.");
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
            ctx.Log($"❌ Ошибка парсинга install_steps {ctx.PluginName}: {ex.Message}");
            return false;
        }
        catch (JsonException ex)
        {
            ctx.Log($"❌ Невалидный JSON install_steps {ctx.PluginName}: {ex.Message}");
            return false;
        }

        if (steps.Count == 0)
        {
            ctx.Log($"[!] У плагина {ctx.PluginName} список шагов пуст.");
            return false;
        }

        using var tx = new InstallTransaction(ctx);
        ctx.Transaction = tx;
        try
        {
            for (int i = 0; i < steps.Count; i++)
            {
                var step = steps[i];
                ctx.Log($"   ── шаг {i + 1}/{steps.Count}: {step.GetType().Name.Replace("Step", "")}");
                var r = step.Execute(ctx);
                tx.AddArtifacts(r.Artifacts);
                if (!r.Success)
                {
                    ctx.Log($"❌ Шаг провален: {r.Error}");
                    return false;
                }
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
        }
        catch (Exception ex)
        {
            ctx.Log($"⚠ Установка прошла, но не удалось записать манифест: {ex.Message}");
            // не считаем это ошибкой установки — файлы уже на местах
        }

        ctx.Log($"✅ {ctx.PluginName} установлен успешно.");
        return true;
    }

}
