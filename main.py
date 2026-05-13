# main.py
# Точка входа Aksiom Installer (PyQt6).

import os
import sys
import io

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from styles import GLOBAL_QSS
from main_window import AksiomInstaller, SplashDialog, is_admin, relaunch_as_admin


def _force_utf8_streams():
    """Гарантируем UTF-8 stdout/stderr (как в оригинале)."""
    try:
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding='utf-8')
        if isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass


def main():
    _force_utf8_streams()

    # На Windows гарантируем правильную группировку в панели задач
    # и подхват иконки из exe (AppUserModelID).
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "AksiomInstaller.AE.PluginsInstaller.7"
            )
        except Exception:
            pass

    # Включаем поддержку HiDPI до создания QApplication
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    app = QApplication(sys.argv)
    app.setApplicationName("Aksiom Installer")
    app.setOrganizationName("Aks-iom")

    # Глобальный тёмный QSS
    app.setStyleSheet(GLOBAL_QSS)

    # Splash показываем СРАЗУ — до создания AksiomInstaller (которое
    # выполняет загрузку plugins.json, lang.json, custom-конфигов и т.д.).
    # processEvents() гарантирует, что окно реально отрисуется на экране
    # до начала тяжёлой инициализации.
    splash = SplashDialog()
    splash.show()
    splash.raise_()
    app.processEvents()

    # Передаём splash в окно, чтобы оно НЕ создавало второй splash
    # и закрыло этот в _close_splash_and_show.
    window = AksiomInstaller(splash=splash)
    # window.show() вызывается уже изнутри _close_splash_and_show,
    # после закрытия сплэш-экрана.

    sys.exit(app.exec())


if __name__ == "__main__":
    # UAC-эскалация: если не админ — перезапускаемся с правами и выходим.
    if not is_admin():
        relaunch_as_admin()
        sys.exit(0)

    main()
