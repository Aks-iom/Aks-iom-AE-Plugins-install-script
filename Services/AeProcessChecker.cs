using System;
using System.Diagnostics;

namespace AEPluginInstaller.Services;

public static class AeProcessChecker
{
    /// <summary>True, если в системе запущен процесс AfterFX.exe.</summary>
    public static bool IsAeRunning()
    {
        if (!OperatingSystem.IsWindows()) return false;
        try
        {
            var procs = Process.GetProcessesByName("AfterFX");
            try { return procs.Length > 0; }
            finally { foreach (var p in procs) p.Dispose(); }
        }
        catch { return false; }
    }
}
