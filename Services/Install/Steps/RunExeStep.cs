using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Text.Json;

namespace AEPluginInstaller.Services.Install.Steps;

/// <summary>
/// JSON:
/// <code>
/// {"type":"run_exe","path":"{SRC_DIR}/Setup.exe","args":["/SILENT"],"wait":true,"ignore_codes":[3010],"show_window":false}
/// </code>
/// Запускает .exe / .bat / .cmd-инсталлер. Артефакт ExeInstall — без отката
/// (пользователю придётся снести через «Программы и компоненты», если установка
/// дала сбой позже).
///
/// Порт Python-шага <c>run_exe.py</c>: процесс запускается напрямую
/// (UseShellExecute = false), как <c>subprocess.run(cmd, creationflags=CREATE_NO_WINDOW)</c>.
/// Приложение уже работает с правами администратора (requireAdministrator в
/// app.manifest), поэтому дочерний инсталлер наследует elevation — ShellExecute
/// для UAC не нужен.
/// </summary>
public class RunExeStep : IInstallStep
{
    public string Path { get; init; } = "";
    public List<string> Args { get; init; } = new();
    public bool Wait { get; init; } = true;
    public HashSet<int> IgnoreCodes { get; init; } = new();

    /// <summary>
    /// Показывать окно дочернего процесса. По умолчанию false — как CREATE_NO_WINDOW
    /// в Python-версии (скрывает мелькающее консольное окно у silent-инсталлеров).
    /// Для интерактивных GUI-инсталлеров значения это не меняет — их собственные
    /// окна показываются в любом случае.
    /// </summary>
    public bool ShowWindow { get; init; }

    public StepResult Execute(InstallContext ctx)
    {
        var arts = new List<Artifact>();
        try
        {
            var exe = ctx.Expand(Path);
            var args = Args.Select(a => ctx.Expand(a)).ToList();

            if (!System.IO.File.Exists(exe))
                return StepResult.Fail($"run_exe: файл не найден: {exe}", arts);

            // Рабочая папка = папка самого инсталлятора. Критично для инсталлеров,
            // вызывающих соседние файлы по относительным путям.
            var workDir = System.IO.Path.GetDirectoryName(exe) ?? "";

            ctx.Log($"   ▶ Запуск {exe}");
            ctx.Log("   ⚠ Может потребоваться ручное взаимодействие в окне инсталлера.");

            // UseShellExecute = false: запускаем процесс напрямую (как Python subprocess).
            // CreateNoWindow / ArgumentList / WorkingDirectory работают корректно
            // только в этом режиме. UAC не нужен — мы уже elevated.
            var psi = new ProcessStartInfo
            {
                UseShellExecute = false,
                CreateNoWindow = !ShowWindow,
                WorkingDirectory = workDir
            };

            // .bat / .cmd напрямую через CreateProcess не запускаются — заворачиваем в cmd.exe.
            var ext = System.IO.Path.GetExtension(exe).ToLowerInvariant();
            if (ext == ".bat" || ext == ".cmd")
            {
                psi.FileName = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe";
                psi.ArgumentList.Add("/c");
                psi.ArgumentList.Add(exe);
            }
            else
            {
                psi.FileName = exe;
            }
            foreach (var a in args) psi.ArgumentList.Add(a);

            var proc = Process.Start(psi);
            if (proc == null)
                return StepResult.Fail($"run_exe: Process.Start вернул null для {exe}", arts);

            if (Wait)
            {
                proc.WaitForExit();
                if (proc.ExitCode != 0 && !IgnoreCodes.Contains(proc.ExitCode))
                    return StepResult.Fail($"run_exe: '{exe}' exited with code {proc.ExitCode}", arts);
            }
            // При Wait == false — fire-and-forget (как subprocess.Popen в Python).

            arts.Add(Artifact.ExeInstall(exe, args));
            return StepResult.Ok(arts);
        }
        catch (System.ComponentModel.Win32Exception ex)
        {
            return StepResult.Fail($"run_exe: cannot launch: {ex.Message}", arts);
        }
        catch (Exception ex)
        {
            return StepResult.Fail($"run_exe failed: {ex.Message}", arts);
        }
    }

    public class Factory : IInstallStepFactory
    {
        public string TypeName => "run_exe";
        public IInstallStep Create(JsonElement node)
        {
            var step = new RunExeStep
            {
                Path = node.GetProperty("path").GetString() ?? "",
                Wait = !node.TryGetProperty("wait", out var w) || w.GetBoolean(),
                ShowWindow = node.TryGetProperty("show_window", out var sw) && sw.GetBoolean()
            };
            if (node.TryGetProperty("args", out var args))
            {
                foreach (var a in args.EnumerateArray())
                    step.Args.Add(a.GetString() ?? "");
            }
            if (node.TryGetProperty("ignore_codes", out var codes))
            {
                foreach (var c in codes.EnumerateArray())
                    step.IgnoreCodes.Add(c.GetInt32());
            }
            // По умолчанию игнорируем 3010 (требуется перезагрузка — это успех).
            // Совпадает с _INSTALLER_SUCCESS_CODES = {0, 3010} в Python.
            if (step.IgnoreCodes.Count == 0) step.IgnoreCodes.Add(3010);
            return step;
        }
    }
}
