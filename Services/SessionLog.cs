using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using AEPluginInstaller.Services.Install;

namespace AEPluginInstaller.Services;

/// <summary>
/// Уровень одной строки детализированного лога.
/// </summary>
public enum SessionLogLevel { Debug, Info, Warn, Error }

/// <summary>
/// Метаданные одной попытки установки. Передаются в <see cref="SessionLog.BeginAttempt"/>
/// и попадают в шапку секции.
/// </summary>
public sealed class AttemptMeta
{
    public string AeVersion { get; init; } = "";
    public string AeInstallPath { get; init; } = "";
    public IReadOnlyList<string> Plugins { get; init; } = Array.Empty<string>();
    public bool Overwrite { get; init; }
    public bool TelemetryEnabled { get; init; } = true;
}

/// <summary>
/// Итог одной попытки. Используется в <see cref="SessionLog.EndAttempt"/>.
/// </summary>
public sealed class AttemptOutcome
{
    public int Ok { get; init; }
    public int Failed { get; init; }
    public bool Cancelled { get; init; }
    public TimeSpan Duration { get; init; }

    public bool IsSuccess => !Cancelled && Failed == 0;
}

/// <summary>
/// Накапливает детальный лог всех попыток установки. Файл лежит в %AppData%\AEPluginInstaller\session_log.txt
/// и сохраняется между запусками — чтобы отправляемый в телеметрию файл содержал полную историю
/// попыток данного UserId, согласованно с счётчиками TotalAttempts/FailedAttempts.
/// </summary>
public class SessionLog
{
    private readonly UserProgress _progress;
    private readonly string _logPath;
    private readonly object _lock = new();

    /// <summary>Номер текущей открытой попытки (0 если попытка не открыта).</summary>
    private int _currentAttempt;

    public SessionLog(UserProgress progress)
    {
        _progress = progress;
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "AEPluginInstaller");
        Directory.CreateDirectory(dir);
        _logPath = Path.Combine(dir, "session_log.txt");
    }

    public string LogFilePath => _logPath;

    /// <summary>
    /// Открывает новую попытку: инкрементит TotalAttempts, печатает разделитель и метаданные.
    /// Возвращает номер попытки.
    /// </summary>
    public int BeginAttempt(AttemptMeta meta)
    {
        lock (_lock)
        {
            _progress.Data.TotalAttempts++;
            _progress.Save();
            _currentAttempt = _progress.Data.TotalAttempts;

            var now = DateTime.Now;
            var sb = new StringBuilder();
            // Пустая строка перед заголовком, если файл уже содержит предыдущие попытки
            if (File.Exists(_logPath) && new FileInfo(_logPath).Length > 0)
            {
                sb.AppendLine();
                sb.AppendLine();
            }
            const string bar = "================================================================";
            sb.AppendLine(bar);
            sb.AppendLine($"=== Attempt {_currentAttempt}: {now:yyyy-MM-dd HH:mm:ss} ===");
            sb.AppendLine(bar);
            sb.AppendLine("[Session]");
            sb.AppendLine($"  User ID         : {_progress.Data.UserId}");
            sb.AppendLine($"  App version     : {GetAppVersion()}");
            sb.AppendLine($"  OS              : {Environment.OSVersion} ({(Environment.Is64BitOperatingSystem ? "x64" : "x86")})");
            sb.AppendLine($"  CLR             : {Environment.Version}");
            sb.AppendLine($"  Machine         : {Environment.MachineName}");
            sb.AppendLine($"  Culture         : {System.Globalization.CultureInfo.CurrentUICulture.Name}");
            sb.AppendLine($"  Telemetry       : {(meta.TelemetryEnabled ? "enabled" : "disabled")}");
            sb.AppendLine($"  Total attempts  : {_progress.Data.TotalAttempts}");
            sb.AppendLine($"  Failed attempts : {_progress.Data.FailedAttempts}");
            sb.AppendLine();
            sb.AppendLine("[Install target]");
            sb.AppendLine($"  AE version      : {(string.IsNullOrEmpty(meta.AeVersion) ? "(none)" : meta.AeVersion)}");
            sb.AppendLine($"  AE base path    : {(string.IsNullOrEmpty(meta.AeInstallPath) ? "(default)" : meta.AeInstallPath)}");
            sb.AppendLine($"  Overwrite mode  : {(meta.Overwrite ? "yes" : "no")}");
            sb.AppendLine($"  Plugins ({meta.Plugins.Count}):");
            if (meta.Plugins.Count == 0)
                sb.AppendLine("    (empty)");
            else
                foreach (var p in meta.Plugins)
                    sb.AppendLine($"    - {p}");
            sb.AppendLine();
            sb.AppendLine("[Events]");

            AppendRaw(sb.ToString());
            return _currentAttempt;
        }
    }

    /// <summary>
    /// Закрывает текущую попытку: при необходимости инкрементит FailedAttempts,
    /// печатает резюме (Ok/Failed/длительность/Result).
    /// </summary>
    public void EndAttempt(AttemptOutcome outcome)
    {
        lock (_lock)
        {
            if (!outcome.IsSuccess)
            {
                _progress.Data.FailedAttempts++;
                _progress.Save();
            }

            string result = outcome.Cancelled
                ? "CANCELLED"
                : outcome.Failed == 0
                    ? "SUCCESS"
                    : (outcome.Ok > 0 ? "PARTIAL" : "FAILED");

            var sb = new StringBuilder();
            sb.AppendLine();
            sb.AppendLine($"[Summary of Attempt {_currentAttempt}]");
            sb.AppendLine($"  Plugins OK      : {outcome.Ok}");
            sb.AppendLine($"  Plugins FAILED  : {outcome.Failed}");
            sb.AppendLine($"  Duration        : {FormatDuration(outcome.Duration)}");
            sb.AppendLine($"  Result          : {result}");

            AppendRaw(sb.ToString());
            _currentAttempt = 0;
        }
    }

    /// <summary>
    /// Возвращает true, если сейчас открыта секция попытки (между BeginAttempt и EndAttempt).
    /// </summary>
    public bool IsAttemptOpen => _currentAttempt > 0;

    /// <summary>Записывает одну строку события с таймстемпом и уровнем.</summary>
    public void Append(SessionLogLevel level, string msg)
    {
        if (_currentAttempt == 0) return; // вне открытой попытки игнорируем
        if (string.IsNullOrEmpty(msg)) msg = "";
        var ts = DateTime.Now.ToString("HH:mm:ss.fff");
        var lvl = level switch
        {
            SessionLogLevel.Debug => "DEBUG",
            SessionLogLevel.Info  => "INFO ",
            SessionLogLevel.Warn  => "WARN ",
            SessionLogLevel.Error => "ERROR",
            _ => "INFO "
        };
        // Многострочные сообщения (stacktrace) сохраняем как есть — продолжения с отступом
        var lines = msg.Replace("\r\n", "\n").Split('\n');
        var sb = new StringBuilder(msg.Length + 32);
        sb.Append('[').Append(ts).Append("] ").Append(lvl).Append(" | ").AppendLine(lines[0]);
        for (int i = 1; i < lines.Length; i++)
        {
            sb.Append("                          | ").AppendLine(lines[i]);
        }
        AppendRaw(sb.ToString());
    }

    public void Info(string msg)  => Append(SessionLogLevel.Info, msg);
    public void Warn(string msg)  => Append(SessionLogLevel.Warn, msg);
    public void Error(string msg) => Append(SessionLogLevel.Error, msg);
    public void Debug(string msg) => Append(SessionLogLevel.Debug, msg);

    /// <summary>Записывает исключение со стеком вызовов.</summary>
    public void Exception(string context, Exception ex)
    {
        var sb = new StringBuilder();
        sb.Append(context).Append(": ").Append(ex.GetType().FullName).Append(" — ").AppendLine(ex.Message);
        var inner = ex.InnerException;
        int depth = 0;
        while (inner != null && depth < 5)
        {
            sb.Append("  inner: ").Append(inner.GetType().FullName).Append(" — ").AppendLine(inner.Message);
            inner = inner.InnerException;
            depth++;
        }
        if (!string.IsNullOrEmpty(ex.StackTrace))
        {
            sb.AppendLine("  stacktrace:");
            foreach (var line in ex.StackTrace.Replace("\r\n", "\n").Split('\n'))
                sb.Append("    ").AppendLine(line.TrimEnd());
        }
        Append(SessionLogLevel.Error, sb.ToString().TrimEnd());
    }

    /// <summary>Полный текст файла лога (для отправки в Telegram).</summary>
    public string GetFullText()
    {
        lock (_lock)
        {
            try
            {
                if (!File.Exists(_logPath)) return "";
                return File.ReadAllText(_logPath);
            }
            catch (Exception ex)
            {
                return $"[session_log read error: {ex.Message}]";
            }
        }
    }

    /// <summary>Полная очистка истории (на случай ручной кнопки в настройках).</summary>
    public void Clear()
    {
        lock (_lock)
        {
            try { if (File.Exists(_logPath)) File.Delete(_logPath); }
            catch { /* ignore */ }
        }
    }

    private void AppendRaw(string text)
    {
        try
        {
            File.AppendAllText(_logPath, text, Encoding.UTF8);
        }
        catch
        {
            // best-effort: не валим установку из-за лога
        }
    }

    private static string FormatDuration(TimeSpan d)
    {
        if (d.TotalSeconds < 60) return $"{d.TotalSeconds:0.000} s";
        if (d.TotalMinutes < 60) return $"{(int)d.TotalMinutes}m {d.Seconds:00}s";
        return $"{(int)d.TotalHours}h {d.Minutes:00}m {d.Seconds:00}s";
    }

    private static string GetAppVersion()
    {
        try
        {
            var asm = Assembly.GetEntryAssembly() ?? Assembly.GetExecutingAssembly();
            var v = asm.GetName().Version?.ToString();
            return string.IsNullOrEmpty(v) ? "unknown" : v!;
        }
        catch { return "unknown"; }
    }
}

/// <summary>Адаптер: <see cref="SessionLog"/> ↔ <see cref="LogLevel"/>.</summary>
internal static class SessionLogAdapter
{
    public static SessionLogLevel Map(LogLevel level) => level switch
    {
        LogLevel.Debug => SessionLogLevel.Debug,
        LogLevel.Info  => SessionLogLevel.Info,
        LogLevel.Warn  => SessionLogLevel.Warn,
        LogLevel.Error => SessionLogLevel.Error,
        _ => SessionLogLevel.Info
    };
}
