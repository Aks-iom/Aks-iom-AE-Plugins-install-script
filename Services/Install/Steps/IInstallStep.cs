using System.Text.Json;

namespace AEPluginInstaller.Services.Install.Steps;

/// <summary>Один атомарный шаг установки. Все шаги stateless.</summary>
public interface IInstallStep
{
    StepResult Execute(InstallContext ctx);
}

/// <summary>Фабрика шага из JSON-узла.</summary>
public interface IInstallStepFactory
{
    string TypeName { get; }
    IInstallStep Create(JsonElement node);
}
