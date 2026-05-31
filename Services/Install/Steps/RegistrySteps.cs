using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using Microsoft.Win32;

namespace AEPluginInstaller.Services.Install.Steps;

/// <summary>JSON: <c>{"type":"import_reg","path":"{SRC_DIR}/keys.reg"}</c>.</summary>
public class ImportRegStep : IInstallStep
{
    public string Path { get; init; } = "";

    public StepResult Execute(InstallContext ctx)
    {
        var arts = new List<Artifact>();
        var reg = ctx.Expand(Path);
        if (!File.Exists(reg)) return StepResult.Fail($"import_reg: file not found: {reg}", arts);
        if (!OperatingSystem.IsWindows()) return StepResult.Fail("import_reg: Windows-only", arts);

        try
        {
            var psi = new ProcessStartInfo("reg.exe", $"import \"{reg}\"")
            {
                UseShellExecute = false,
                RedirectStandardError = true,
                RedirectStandardOutput = true,
                CreateNoWindow = true
            };
            var proc = Process.Start(psi)!;
            if (!proc.WaitForExit(60_000))
            {
                try { proc.Kill(); } catch { }
                return StepResult.Fail("import_reg: reg.exe timed out", arts);
            }
            if (proc.ExitCode != 0)
            {
                var err = proc.StandardError.ReadToEnd().Trim();
                return StepResult.Fail($"import_reg: reg.exe exit {proc.ExitCode}: {err}", arts);
            }

            // Артефакт «логический» — без точного знания всех изменённых ключей не откатимся
            arts.Add(new Artifact
            {
                Type = ArtifactType.ExeInstall,
                Path = reg,
                Extra = { ["kind"] = "reg_import" }
            });
            ctx.Log($"   ✓ Импортирован .reg-файл: {reg}");
            return StepResult.Ok(arts);
        }
        catch (Exception ex) { return StepResult.Fail($"import_reg failed: {ex.Message}", arts); }
    }

    public class Factory : IInstallStepFactory
    {
        public string TypeName => "import_reg";
        public IInstallStep Create(JsonElement node) => new ImportRegStep
        {
            Path = node.GetProperty("path").GetString() ?? ""
        };
    }
}

/// <summary>
/// JSON:
/// <code>
/// {"type":"set_reg_value","hive":"HKLM","key":"Software\\Adobe\\CSXS.11",
///  "name":"PlayerDebugMode","value":"1","value_type":"REG_SZ","wow64":true}
/// </code>
/// </summary>
public class SetRegValueStep : IInstallStep
{
    public string Hive { get; init; } = "HKLM";
    public string Key { get; init; } = "";
    public string Name { get; init; } = "";
    public JsonElement RawValue { get; init; }
    public string ValueType { get; init; } = "REG_SZ";
    public bool Wow64 { get; init; }

    public StepResult Execute(InstallContext ctx)
    {
        var arts = new List<Artifact>();
        if (!OperatingSystem.IsWindows())
            return StepResult.Fail("set_reg_value: Windows-only", arts);

        try
        {
            var hive = Hive.ToUpperInvariant() switch
            {
                "HKLM" or "HKEY_LOCAL_MACHINE" => RegistryHive.LocalMachine,
                "HKCU" or "HKEY_CURRENT_USER" => RegistryHive.CurrentUser,
                _ => throw new ArgumentException($"Unknown hive: {Hive}")
            };
            var view = Wow64 ? RegistryView.Registry64 : RegistryView.Default;

            using var baseKey = RegistryKey.OpenBaseKey(hive, view);
            using var k = baseKey.CreateSubKey(Key, writable: true)
                          ?? throw new InvalidOperationException($"Cannot open/create key: {Key}");

            var kind = ValueType switch
            {
                "REG_SZ" => RegistryValueKind.String,
                "REG_DWORD" => RegistryValueKind.DWord,
                "REG_EXPAND_SZ" => RegistryValueKind.ExpandString,
                _ => throw new ArgumentException($"Unsupported value_type: {ValueType}")
            };

            object value = kind switch
            {
                RegistryValueKind.DWord => RawValue.ValueKind switch
                {
                    JsonValueKind.Number => RawValue.GetInt32(),
                    JsonValueKind.String when int.TryParse(RawValue.GetString(), out var i) => i,
                    _ => throw new ArgumentException("REG_DWORD: invalid value")
                },
                _ => RawValue.ValueKind == JsonValueKind.String
                    ? RawValue.GetString() ?? ""
                    : RawValue.ToString() ?? ""
            };

            k.SetValue(Name, value, kind);

            var full = $"{Hive}\\{Key}\\{Name}";
            arts.Add(Artifact.RegValue(full, Wow64));
            ctx.Log($"   ✓ Запись в реестр: {full} = {value}");
            return StepResult.Ok(arts);
        }
        catch (Exception ex) { return StepResult.Fail($"set_reg_value failed: {ex.Message}", arts); }
    }

    public class Factory : IInstallStepFactory
    {
        public string TypeName => "set_reg_value";
        public IInstallStep Create(JsonElement node) => new SetRegValueStep
        {
            Hive = node.GetProperty("hive").GetString() ?? "HKLM",
            Key = node.GetProperty("key").GetString() ?? "",
            Name = node.GetProperty("name").GetString() ?? "",
            RawValue = node.TryGetProperty("value", out var v) ? v.Clone() : default,
            ValueType = node.TryGetProperty("value_type", out var vt) ? vt.GetString() ?? "REG_SZ" : "REG_SZ",
            Wow64 = node.TryGetProperty("wow64", out var w) && w.GetBoolean()
        };
    }
}

/// <summary>JSON: <c>{"type":"enable_cep_debug"}</c> — включает PlayerDebugMode во всех CSXS.</summary>
public class EnableCepDebugStep : IInstallStep
{
    private static readonly string[] CsxsBranches =
        { "CSXS.10", "CSXS.11", "CSXS.12", "CSXS.13", "CSXS.14", "CSXS.15", "CSXS.16" };

    public StepResult Execute(InstallContext ctx)
    {
        var arts = new List<Artifact>();
        if (!OperatingSystem.IsWindows()) return StepResult.Fail("enable_cep_debug: Windows-only", arts);

        var ok = 0;
        foreach (var csxs in CsxsBranches)
        {
            var keyPath = $"Software\\Adobe\\{csxs}";
            try
            {
                using var baseKey = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64);
                using var k = baseKey.CreateSubKey(keyPath, writable: true)!;
                k.SetValue("PlayerDebugMode", "1", RegistryValueKind.String);
                arts.Add(Artifact.RegValue($"HKLM\\{keyPath}\\PlayerDebugMode", wow64: true));
                ok++;
            }
            catch (Exception ex)
            {
                ctx.Log($"   ! CSXS не доступен: {csxs} ({ex.Message})");
            }
        }
        if (ok == 0) return StepResult.Fail("enable_cep_debug: no CSXS keys", arts);
        ctx.Log($"   ✓ CEP debug включён для {ok} веток CSXS");
        return StepResult.Ok(arts);
    }

    public class Factory : IInstallStepFactory
    {
        public string TypeName => "enable_cep_debug";
        public IInstallStep Create(JsonElement node) => new EnableCepDebugStep();
    }
}
