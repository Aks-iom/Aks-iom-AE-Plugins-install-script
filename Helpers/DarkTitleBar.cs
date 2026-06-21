using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace AEPluginInstaller.Helpers;

/// <summary>
/// Включает тёмный системный title bar на Windows 10 2004+ / Windows 11.
/// Использует нативный DWM-аттрибут — стандартный способ Microsoft.
/// </summary>
public static class DarkTitleBar
{
    // Аттрибут DWMWA_USE_IMMERSIVE_DARK_MODE.
    // На Win10 20H1 / Win11 он 20, на Win10 1809..1909 — 19. Пробуем оба.
    private const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20;
    private const int DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19;

    [DllImport("dwmapi.dll", PreserveSig = true)]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

    public static void Apply(Window window)
    {
        if (!OperatingSystem.IsWindows()) return;
        try
        {
            // Если окно ещё не отрисовано, ждём и пробуем снова
            var helper = new WindowInteropHelper(window);
            if (helper.Handle == IntPtr.Zero)
            {
                window.SourceInitialized += (_, _) => Apply(window);
                return;
            }

            int useDark = 1;
            // Пробуем новый аттрибут; если не сработал — старый
            if (DwmSetWindowAttribute(helper.Handle, DWMWA_USE_IMMERSIVE_DARK_MODE, ref useDark, sizeof(int)) != 0)
            {
                DwmSetWindowAttribute(helper.Handle, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, ref useDark, sizeof(int));
            }
        }
        catch { /* не критично */ }
    }
}
