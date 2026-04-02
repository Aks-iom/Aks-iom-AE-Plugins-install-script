@echo off
chcp 65001 >nul
title Сборка исполняемого файла

:start
cls
echo Переход в рабочую директорию...
cd /d "C:\Users\Sergey-MSI\Desktop\aepluhins"

echo Запуск PyInstaller...
pyinstaller --noconsole --onefile --uac-admin --icon=logo.ico --add-data "logo.ico;." main.py

echo.
echo Процесс завершен. Проверьте папку dist для получения готового .exe файла.
echo.
echo Нажмите Enter (или любую другую клавишу) для повторной сборки...
pause >nul
goto start