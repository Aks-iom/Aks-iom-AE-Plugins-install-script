@echo off
chcp 65001 >nul
title Сборка исполняемого файла

:start
cd /d "%~dp0"

echo Запуск PyInstaller...
pyinstaller --noconsole --onefile --uac-admin --icon=logo.ico --add-data "logo.ico;." AE_plugins_installer.py

echo.
echo Процесс завершен. Проверьте папку dist для получения готового .exe файла.

pause >nul
goto start