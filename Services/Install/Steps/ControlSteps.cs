using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;

namespace AEPluginInstaller.Services.Install.Steps;

/// <summary>JSON: <c>{"type":"kill_process","name":"Maxon App.exe","delay":4}</c>.</summary>
public class KillProcessStep : IInstallStep
{
    public string Name { get; init; } = "";
    public double Delay { get; init; }

    public StepResult Execute(InstallContext ctx)
    {
        if (Delay > 0) Thread.Sleep(TimeSpan.FromSeconds(Delay));
        if (!OperatingSystem.IsWindows()) return StepResult.Ok();

        var procName = System.IO.Path.GetFileNameWithoutExtension(Name);
        Process[] procs;
        try { procs = Process.GetProcessesByName(procName); }
        catch (Exception ex)
        {
            return StepResult.Fail($"kill_process: не удалось перечислить процессы '{Name}': {ex.Message}");
        }

        if (procs.Length == 0)
        {
            ctx.LogDebug($"kill_process: процесс '{Name}' не запущен — нечего убивать");
            return StepResult.Ok();
        }

        var failed = new List<string>();
        var stillAlive = new List<int>();
        foreach (var p in procs)
        {
            try
            {
                p.Kill(entireProcessTree: true);
                if (!p.WaitForExit(5000))
                    stillAlive.Add(p.Id);
            }
            catch (Exception ex)
            {
                failed.Add($"pid={p.Id}: {ex.Message}");
            }
            finally { p.Dispose(); }
        }

        if (failed.Count > 0)
            return StepResult.Fail(
                $"kill_process '{Name}': не удалось убить {failed.Count}/{procs.Length} процесс(ов): {string.Join("; ", failed)}");

        if (stillAlive.Count > 0)
            return StepResult.Fail(
                $"kill_process '{Name}': {stillAlive.Count} процесс(ов) не завершились за 5с (pids: {string.Join(",", stillAlive)})");

        ctx.Log($"   ✓ Процесс остановлен: {Name} ({procs.Length} шт.)");
        return StepResult.Ok();
    }

    public class Factory : IInstallStepFactory
    {
        public string TypeName => "kill_process";
        public IInstallStep Create(JsonElement node) => new KillProcessStep
        {
            Name = node.GetProperty("name").GetString() ?? "",
            Delay = node.TryGetProperty("delay", out var d) ? d.GetDouble() : 0
        };
    }
}

/// <summary>
/// JSON:
/// <code>
/// {"type":"if","condition":"options.old_rsmb","then":[...],"else":[...]}
/// </code>
/// Условия: <c>options.X</c>, <c>!options.X</c>, <c>options.X == 'value'</c>.
/// Артефакты выполненных вложенных шагов «всплывают» в транзакцию.
/// </summary>
public class IfStep : IInstallStep
{
    public string Condition { get; init; } = "";
    public List<IInstallStep> ThenSteps { get; init; } = new();
    public List<IInstallStep> ElseSteps { get; init; } = new();

    private static readonly Regex CondRe = new(
        @"^\s*(!?)\s*([\w\.]+)\s*(?:==\s*(['""]?)([^'""]+)\3)?\s*$",
        RegexOptions.Compiled);

    public StepResult Execute(InstallContext ctx)
    {
        var arts = new List<Artifact>();
        try
        {
            var (cond, parsed) = Eval(Condition, ctx);
            if (!parsed)
                return StepResult.Fail($"if: не понял условие '{Condition}'", arts);
            var branch = cond ? ThenSteps : ElseSteps;
            ctx.Log($"   ⟶ if({Condition}) = {cond}, выполняю {branch.Count} шагов");

            foreach (var step in branch)
            {
                var r = step.Execute(ctx);
                arts.AddRange(r.Artifacts);
                if (!r.Success)
                    return StepResult.Fail($"if-branch step failed: {r.Error}", arts);
            }
            return StepResult.Ok(arts);
        }
        catch (Exception ex)
        {
            return StepResult.Fail($"if step failed: {ex.Message}", arts);
        }
    }

    private static (bool value, bool parsed) Eval(string cond, InstallContext ctx)
    {
        var m = CondRe.Match(cond);
        if (!m.Success) return (false, false);

        var negate = m.Groups[1].Value == "!";
        var dotted = m.Groups[2].Value;
        var expected = m.Groups[4].Success ? m.Groups[4].Value : null;

        var actual = ctx.GetBoolOption(dotted);

        if (expected == null) return (negate ? !actual : actual, true);

        // равенство строк — берём raw value
        var parts = dotted.Split('.');
        if (parts.Length > 0 && parts[0] == "options") parts = parts[1..];
        object? cur = ctx.Options;
        foreach (var p in parts)
        {
            if (cur is IDictionary<string, object> d && d.TryGetValue(p, out var next)) cur = next;
            else { cur = null; break; }
        }
        var eq = (cur?.ToString() ?? "") == expected;
        return (negate ? !eq : eq, true);
    }

    public class Factory : IInstallStepFactory
    {
        public string TypeName => "if";
        public IInstallStep Create(JsonElement node)
        {
            var ifStep = new IfStep { Condition = node.GetProperty("condition").GetString() ?? "" };
            if (node.TryGetProperty("then", out var t))
                ifStep.ThenSteps.AddRange(StepBuilder.BuildSteps(t));
            if (node.TryGetProperty("else", out var e))
                ifStep.ElseSteps.AddRange(StepBuilder.BuildSteps(e));
            return ifStep;
        }
    }
}
