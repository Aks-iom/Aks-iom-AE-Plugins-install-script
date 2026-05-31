using System.Collections.Generic;
using System.Text.Json;

namespace AEPluginInstaller.Services.Install.Steps;

/// <summary>Регистрация и фабрика шагов из JSON-описания.</summary>
public static class StepBuilder
{
    private static readonly Dictionary<string, IInstallStepFactory> Registry = new()
    {
        ["copy_file"] = new CopyFileStep.Factory(),
        ["copy_dir"] = new CopyDirStep.Factory(),
        ["extract_zip"] = new ExtractZipStep.Factory(),
        ["run_exe"] = new RunExeStep.Factory(),
        ["import_reg"] = new ImportRegStep.Factory(),
        ["set_reg_value"] = new SetRegValueStep.Factory(),
        ["enable_cep_debug"] = new EnableCepDebugStep.Factory(),
        ["kill_process"] = new KillProcessStep.Factory(),
        ["if"] = new IfStep.Factory()
    };

    /// <summary>Парсит массив шагов. Бросает <see cref="StepParseException"/> на ошибках.</summary>
    public static List<IInstallStep> BuildSteps(JsonElement stepsArray)
    {
        var result = new List<IInstallStep>();
        if (stepsArray.ValueKind != JsonValueKind.Array) return result;

        var i = 0;
        foreach (var node in stepsArray.EnumerateArray())
        {
            i++;
            if (node.ValueKind != JsonValueKind.Object)
                throw new StepParseException($"step #{i}: must be an object");
            if (!node.TryGetProperty("type", out var typeEl))
                throw new StepParseException($"step #{i}: missing 'type'");
            var type = typeEl.GetString();
            if (string.IsNullOrEmpty(type) || !Registry.TryGetValue(type, out var factory))
                throw new StepParseException($"step #{i}: unknown type '{type}'");
            try
            {
                result.Add(factory.Create(node));
            }
            catch (KeyNotFoundException knf)
            {
                throw new StepParseException($"step #{i} ({type}): missing required field {knf.Message}");
            }
        }
        return result;
    }
}

public class StepParseException : System.Exception
{
    public StepParseException(string message) : base(message) { }
}
