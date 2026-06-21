using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;

namespace AEPluginInstaller.Services.Install.Steps;

/// <summary>
/// JSON:
/// <code>
/// {"type":"run_exe","path":"{SRC_DIR}/Setup.exe","args":["/SILENT"],"wait":true,
///  "ignore_codes":[3010],"show_window":false,
///  "timeout_sec":1800,
///  "verify_path":"C:/Program Files/BorisFX/...",
///  "skip_if_exists":"C:/Program Files/BorisFX/..."}
/// </code>
/// Запускает .exe / .bat / .cmd-инсталлер. Артефакт ExeInstall — без отката
/// (пользователю придётся снести через «Программы и компоненты», если установка
/// дала сбой позже).
/// </summary>
public class RunExeStep : IInstallStep
{
    public string Path { get; init; } = "";
    public List<string> Args { get; init; } = new();
    public bool Wait { get; init; } = true;
    public HashSet<int> IgnoreCodes { get; init; } = new();
    public bool ShowWindow { get; init; }

    /// <summary>Таймаут ожидания процесса в секундах. 0 = без таймаута.</summary>
    public int TimeoutSec { get; init; }

    /// <summary>Если задан, после успешного завершения exe проверяем, что путь существует.</summary>
    public string VerifyPath { get; init; } = "";

    /// <summary>Если задан и путь уже существует — шаг пропускается (идемпотентность).</summary>
    public string SkipIfExists { get; init; } = "";

    public StepResult Execute(InstallContext ctx)
    {
        var arts = new List<Artifact>();
        try
        {
            var exe = ctx.Expand(Path);
            var args = Args.Select(a => ctx.Expand(a)).ToList();

            if (!File.Exists(exe))
                return StepResult.Fail($"run_exe: файл не найден: {exe}", arts);

            // --- Идемпотентность: уже установлено -> skip ---
            if (!string.IsNullOrEmpty(SkipIfExists))
            {
                var skipPath = ctx.Expand(SkipIfExists);
                if (File.Exists(skipPath) || Directory.Exists(skipPath))
                {
                    ctx.Log($"   ⏭ Уже установлено ({skipPath}) — пропуск");
                    return StepResult.Ok(arts);
                }
            }

            var workDir = System.IO.Path.GetDirectoryName(exe) ?? "";

            ctx.Log($"   ▶ Запуск {exe}");
            ctx.Log("   ⚠ Может потребоваться ручное взаимодействие в окне инсталлера.");

            var ext = System.IO.Path.GetExtension(exe).ToLowerInvariant();
            var isScript = ext == ".bat" || ext == ".cmd";

            // Снимок самого свежего лога bat ДО запуска — чтобы потом приклеить только новые
            DateTime logCutoff = isScript ? DateTime.UtcNow : DateTime.MinValue;

            var psi = new ProcessStartInfo
            {
                UseShellExecute = false,
                CreateNoWindow = !ShowWindow && !isScript,
                WorkingDirectory = workDir
            };

            if (isScript)
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
                var ct = ctx.Cancel;
                var timedOut = false;
                var killedByCancel = false;

                if (TimeoutSec > 0)
                {
                    // Циклом ждём по 1 сек, проверяя cancel-токен и общий таймаут.
                    var deadline = DateTime.UtcNow.AddSeconds(TimeoutSec);
                    while (!proc.WaitForExit(1000))
                    {
                        if (ct.IsCancellationRequested) { killedByCancel = true; break; }
                        if (DateTime.UtcNow >= deadline) { timedOut = true; break; }
                    }
                }
                else
                {
                    while (!proc.WaitForExit(1000))
                    {
                        if (ct.IsCancellationRequested) { killedByCancel = true; break; }
                    }
                }

                if (killedByCancel || timedOut)
                {
                    var reason = killedByCancel ? "отмена пользователем" : $"таймаут {TimeoutSec}с";
                    ctx.Log($"   ⏹ Завершаем дерево процессов ({reason})...");
                    KillProcessTree(proc.Id);
                    try { proc.WaitForExit(5000); } catch { }

                    if (isScript) TailRecentBatLog(ctx, logCutoff);
                    return StepResult.Fail($"run_exe: {reason} — '{exe}'", arts);
                }

                if (isScript) TailRecentBatLog(ctx, logCutoff);

                if (proc.ExitCode != 0 && !IgnoreCodes.Contains(proc.ExitCode))
                    return StepResult.Fail($"run_exe: '{exe}' {FormatExitCode(proc.ExitCode)}", arts);
            }
            else
            {
                // Wait == false — fire-and-forget. Регистрируем артефакт, но честно
                // предупреждаем: успех не верифицирован — мы не знаем, чем закончится exe.
                ctx.LogWarn($"run_exe wait=false: '{exe}' запущен в фоне, результат не верифицирован. " +
                    "Если что-то пойдёт не так — откат установки может быть неполным.");
            }

            // --- Post-install verify ---
            if (Wait && !string.IsNullOrEmpty(VerifyPath))
            {
                var vp = ctx.Expand(VerifyPath);
                if (!File.Exists(vp) && !Directory.Exists(vp))
                    return StepResult.Fail(
                        $"run_exe: exit 0, но verify_path не найден: {vp}", arts);
                ctx.Log($"   ✓ verify_path найден: {vp}");
            }

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

    /// <summary>
    /// Преобразует exit-код процесса в понятную человеку строку.
    /// NTSTATUS (0xC...) обычно означают аварийное завершение — Windows
    /// сообщает их как отрицательные int. Перевод значимо помогает на репортах вида
    /// "exited with code -1073741819" (это AV в инсталлере, не вина нашего кода).
    /// </summary>
    private static string FormatExitCode(int code)
    {
        var hex = $"0x{(uint)code:X8}";
        var desc = (uint)code switch
        {
            0xC0000005 => "Access Violation — инсталлер аварийно завершился (проблема в самом инсталлере)",
            0xC000013A => "прерван пользователем (Ctrl+C)",
            0xC0000017 => "не хватает памяти",
            0xC0000142 => "ошибка инициализации DLL — возможно, не хватает Visual C++ Redistributable",
            0xC0000409 => "stack buffer overrun — крэш инсталлера",
            0xC0000374 => "повреждение кучи — крэш инсталлера",
            0xC0000135 => "не найден DLL — возможно, не хватает Visual C++ Redistributable",
            _ => null
        };
        return desc != null
            ? $"завершился с кодом {code} ({hex}): {desc}"
            : $"exited with code {code} ({hex})";
    }

    /// <summary>
    private static void TailRecentBatLog(InstallContext ctx, DateTime cutoff)
    {
        try
        {
            var dir = System.IO.Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "AEPluginInstaller", "logs");
            if (!Directory.Exists(dir)) return;

            var latest = new DirectoryInfo(dir)
                .GetFiles("*.log")
                .Where(f => f.LastWriteTimeUtc >= cutoff)
                .OrderByDescending(f => f.LastWriteTimeUtc)
                .FirstOrDefault();
            if (latest == null) return;

            ctx.Log($"   — лог bat: {latest.Name} —");
            // Читаем последние ~80 строк — не больше, чтобы не засорять UI
            string[] lines;
            try { lines = File.ReadAllLines(latest.FullName); }
            catch { return; }
            const int maxLines = 80;
            int start = Math.Max(0, lines.Length - maxLines);
            if (start > 0) ctx.Log($"   ... (пропущено {start} строк)");
            for (int i = start; i < lines.Length; i++)
                ctx.Log("   │ " + lines[i]);
            ctx.Log("   — конец лога —");
        }
        catch { /* лог best-effort */ }
    }

    /// <summary>
    /// Убивает процесс и всё его дерево через taskkill /T /F.
    /// Возвращает без ожидания подтверждения.
    /// </summary>
    private static void KillProcessTree(int pid)
    {
        try
        {
            var psi = new ProcessStartInfo("taskkill", $"/PID {pid} /T /F")
            {
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            using var k = Process.Start(psi);
            k?.WaitForExit(5000);
        }
        catch { }
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
                ShowWindow = node.TryGetProperty("show_window", out var sw) && sw.GetBoolean(),
                TimeoutSec = node.TryGetProperty("timeout_sec", out var ts) ? ts.GetInt32() : 0,
                VerifyPath = node.TryGetProperty("verify_path", out var vp) ? vp.GetString() ?? "" : "",
                SkipIfExists = node.TryGetProperty("skip_if_exists", out var se) ? se.GetString() ?? "" : ""
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
            if (step.IgnoreCodes.Count == 0) step.IgnoreCodes.Add(3010);
            return step;
        }
    }
}
