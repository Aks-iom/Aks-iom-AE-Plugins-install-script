@echo off
title Build AE_plugins_installer

REM 1. Requesting Administrator privileges
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process '%~dpnx0' -Verb RunAs"
    exit /b
)

REM 2. Change directory to the script's location
cd /d "%~dp0"

:loop
cls
echo ========================================================
echo [1/3] Terminating AE_plugins_installer.exe...
echo ========================================================
taskkill /F /IM AE_plugins_installer.exe >nul 2>&1

if %errorLevel% equ 0 (
    echo Process terminated successfully.
) else (
    echo Process not found.
)

echo.
echo ========================================================
echo [2/3] Running PyInstaller...
echo ========================================================
"C:\Users\Sergey-MSI\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts\pyinstaller.exe" --noconsole --onefile --uac-admin --icon=logo.ico --add-data "logo.ico;." --splash splash.png --collect-all customtkinter AE_plugins_installer.py

echo.
echo ========================================================
echo [3/3] Build finished.
echo Press SPACEBAR to restart the process...
echo ========================================================

REM Wait for Spacebar
powershell -command "while ($true) { if ([Console]::KeyAvailable) { $key = [Console]::ReadKey($true); if ($key.Key -eq [ConsoleKey]::Spacebar) { break } } else { Start-Sleep -Milliseconds 50 } }"

goto loop