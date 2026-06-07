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
        try
        {
            if (Delay > 0) Thread.Sleep(TimeSpan.FromSeconds(Delay));
            if (!OperatingSystem.IsWindows()) return StepResult.Ok();

            var procName = System.IO.Path.GetFileNameWithoutExtension(Name);
            var procs = Process.GetProcessesByName(procName);
            foreach (var p in procs)
            {
                try { p.Kill(entireProcessTree: true); p.WaitForExit(5000); } catch { }
                finally { p.Dispose(); }
            }
            if (procs.Length > 0)
                ctx.Log($"   ✓ Процесс остановлен: {Name}");
            return StepResult.Ok();
        }
        catch (Exception ex)
        {
            // taskkill редко падает; даже если упал — не считаем шаг провалом
            ctx.Log($"   ! kill_process {Name}: {ex.Message}");
            return StepResult.Ok();
        }
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
            var cond = Eval(Condition, ctx);
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

    private static bool Eval(string cond, InstallContext ctx)
    {
        var m = CondRe.Match(cond);
        if (!m.Success)
        {
            ctx.Log($"   ! if: не понял условие '{cond}', результат = false");
            return false;
        }
        var negate = m.Groups[1].Value == "!";
        var dotted = m.Groups[2].Value;
        var expected = m.Groups[4].Success ? m.Groups[4].Value : null;

        var actual = ctx.GetBoolOption(dotted);

        if (expected == null) return negate ? !actual : actual;

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
        return negate ? !eq : eq;
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
