# -*- coding: utf-8 -*-
"""
main_window.py
Главный класс приложения AksiomInstaller (PyQt6).
Содержит:
  • SplashDialog (без рамки) с тёмным тайтлбаром Windows
  • Загрузку конфигов, языковых файлов и БД плагинов
  • Каркас основного окна (верх — QStackedWidget, низ — глобальный футер)
  • Переключение языка, горячие клавиши русской раскладки
  • Проверку обновлений на GitHub
"""

from __future__ import annotations

import ctypes
import json
import locale
import os
import re
import shutil
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from collections import deque  # [AKSIOM-FIX #6]

from PyQt6.QtCore import (
    QObject,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QGuiApplication, QIcon, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from styles import (
    COLOR_ACCENT,
    COLOR_ACCENT_HOV,
    COLOR_TEXT_MUTED,
    SegmentedButton,
)


# ---------------------------------------------------------------------------
# Версия и URL базы плагинов (вынесено наружу, чтобы импортировать из других модулей)
# ---------------------------------------------------------------------------
CURRENT_VERSION = "Beta 7.0"
DB_URL = (
    "https://raw.githubusercontent.com/Aks-iom/aksiom-installer-data/"
    "refs/heads/main/plugins.json"
)
RELEASES_URL = (
    "https://api.github.com/repos/Aks-iom/Aks-iom-AE-Plugins-install-script/"
    "releases/tags/AE"
)

# ---------------------------------------------------------------------------
# Фолбэк-описания плагинов «старого Red Giant режима».
# При синхронизации plugins.json с GitHub (в _update_db_in_background) база
# может быть перезаписана версией из репозитория Aks-iom, в которой нет
# Universe/Trapcode/MBS. Чтобы наша вкладка не теряла эти три плагина,
# мы делаем merge: добавляем недостающие записи в загруженные данные.
# Если GitHub когда-нибудь начнёт отдавать эти плагины со своими gdrive_id —
# мы оставим его версию как приоритетную и наш фолбэк не применится.
# ---------------------------------------------------------------------------
OLD_RG_MODE_PLUGINS: list[dict] = [
    {
        "name": "Universe",
        "version": "2024.0",
        "bat_path": "Universe\\Universe.bat",
        "needs_version": False,
        "size": "~1,8 GB",
        "md5": None,
        "keywords": ["red giant universe", "universe"],
        "gdrive_id": "PLACEHOLDER_UNIVERSE_GDRIVE_ID",
    },
    {
        "name": "Trapcode",
        "version": "2024.0",
        "bat_path": "Trapcode\\Trapcode.bat",
        "needs_version": False,
        "size": "~970 MB",
        "md5": None,
        "keywords": ["trapcode", "particular", "form"],
        "gdrive_id": "PLACEHOLDER_TRAPCODE_GDRIVE_ID",
    },
    {
        "name": "MBS",
        "version": "2024.0",
        "bat_path": "MBS\\MBS.bat",
        "needs_version": False,
        "size": "~390 MB",
        "md5": None,
        "keywords": ["magic bullet", "mbs", "magic bullet suite"],
        "gdrive_id": "PLACEHOLDER_MBS_GDRIVE_ID",
    },
]


def _merge_old_rg_plugins(data: dict | None) -> dict:
    """
    Гарантирует, что в data['plugins'] присутствуют Universe / Trapcode / MBS.
    Если плагин уже есть в data — оставляем версию из data (приоритет данных
    с GitHub, если их там добавят с актуальными gdrive_id). Если отсутствует —
    добавляем фолбэк из OLD_RG_MODE_PLUGINS.

    Возвращает мутированный data (или новый объект, если data был None/пустой).
    """
    if not isinstance(data, dict):
        data = {"plugins": []}
    plugins_list = data.get("plugins")
    if not isinstance(plugins_list, list):
        plugins_list = []
        data["plugins"] = plugins_list
    existing = {p.get("name") for p in plugins_list if isinstance(p, dict)}
    for fallback in OLD_RG_MODE_PLUGINS:
        if fallback["name"] not in existing:
            plugins_list.append(dict(fallback))  # копия чтобы не делиться ссылкой
    return data


# ---------------------------------------------------------------------------
# Утилита: тёмный тайтлбар Windows через DwmSetWindowAttribute
# ---------------------------------------------------------------------------
def apply_dark_titlebar(hwnd: int) -> None:
    """Включает тёмный режим заголовка окна на Windows 10/11."""
    if sys.platform != "win32":
        return
    try:
        value = ctypes.c_int(1)
        # Атрибут 20 (DWMWA_USE_IMMERSIVE_DARK_MODE) — Windows 10 20H1+
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
        # Атрибут 19 — старый аналог для сборок до 20H1
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 19, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"DwmSetWindowAttribute failed: {exc}")


# ---------------------------------------------------------------------------
# SplashDialog — окно загрузки
# ---------------------------------------------------------------------------
class SplashDialog(QDialog):
    """Сплэш-экран без рамки, показывается до полной инициализации UI."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Frameless + поверх всех + прозрачный фон, чтобы скруглённые края PNG
        # не имели серого «прямоугольника» вокруг.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(False)

        # Путь к splash.png: либо из PyInstaller-бандла (sys._MEIPASS),
        # либо рядом с исходником.
        if getattr(sys, "frozen", False):
            bundle_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        else:
            bundle_dir = os.path.dirname(os.path.abspath(__file__))
        splash_path = os.path.join(bundle_dir, "splash.png")

        pixmap = QPixmap(splash_path)
        if pixmap.isNull():
            # Фолбэк на случай отсутствия файла — пустой Pixmap 500x300,
            # чтобы окно всё равно отрисовалось.
            pixmap = QPixmap(500, 300)
            pixmap.fill(Qt.GlobalColor.transparent)

        # Размер окна равен размеру картинки
        self.setFixedSize(pixmap.size())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        image_label = QLabel(self)
        image_label.setPixmap(pixmap)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        image_label.setStyleSheet("background: transparent;")
        layout.addWidget(image_label)

        # Совместимость со старым кодом (если где-то обращаются к status_label)
        self.status_label = image_label

        # Центрирование на экране
        self._center_on_screen()

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geom = screen.availableGeometry()
        self.move(
            geom.x() + (geom.width() - self.width()) // 2,
            geom.y() + (geom.height() - self.height()) // 2,
        )

    def showEvent(self, event):  # noqa: N802 — Qt API
        super().showEvent(event)
        # Тёмный тайтлбар (на всякий случай — окно без рамки, но WinAPI кэширует тему)
        if sys.platform == "win32":
            QTimer.singleShot(10, lambda: apply_dark_titlebar(int(self.winId())))


# ---------------------------------------------------------------------------
# Диалог первого запуска: выбор пути к After Effects
# ---------------------------------------------------------------------------
def _detect_default_ae_path() -> str:
    """
    Возвращает путь к папке After Effects (Support Files), если найден
    автоматически среди установленных версий. Иначе — пустую строку.
    Сканирует стандартный Adobe-каталог в Program Files.
    """
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    adobe_dir = os.path.join(pf, "Adobe")
    if not os.path.isdir(adobe_dir):
        return ""

    # Ищем подкаталоги вида "Adobe After Effects 20XX" — берём самую новую.
    candidates: list[tuple[str, str]] = []  # (year, full_path)
    try:
        for name in os.listdir(adobe_dir):
            full = os.path.join(adobe_dir, name)
            if not os.path.isdir(full):
                continue
            m = re.match(r"(?i)Adobe After Effects\s*(20\d{2})", name)
            if m:
                candidates.append((m.group(1), full))
    except OSError:
        return ""

    if not candidates:
        return ""

    # Сортируем по году, берём самый свежий
    candidates.sort(key=lambda t: t[0], reverse=True)
    base = candidates[0][1]
    plugins = os.path.join(base, "Support Files", "Plug-ins")
    return plugins if os.path.isdir(plugins) else base


# Регулярка для поиска версии AE в имени папки используется в _detect_default_ae_path


class FirstRunPathDialog(QDialog):
    """
    Диалог первого запуска. Просит у пользователя путь к директории
    After Effects (папке плагинов). Можно нажать «Стандартный путь» —
    он автоматически подставится; либо выбрать свой через «Обзор…».

    Возвращаемое значение через self.result_path():
      • ""       — использовать стандартный путь (приложение само вычислит
                   его при каждой установке/проверке/удалении).
      • <путь>   — пользовательский путь, который будет жёстко задан.
    """

    def __init__(self, current_lang: str = "ru", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lang = current_lang
        self._use_default = True  # по умолчанию — стандартный путь

        is_ru = current_lang == "ru"
        self.setWindowTitle(
            "Первый запуск — путь к After Effects" if is_ru
            else "First run — After Effects path"
        )
        self.setModal(True)
        self.setMinimumWidth(560)

        # Главный layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Заголовок
        title = QLabel(
            "Укажите папку плагинов After Effects" if is_ru
            else "Specify the After Effects plug-ins folder",
            self,
        )
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        # Описание
        desc = QLabel(
            ("Если у вас стандартная установка After Effects — нажмите\n"
             "«Стандартный путь». Если AE установлен в другое место —\n"
             "укажите путь к папке Plug-ins вручную или через «Обзор…».")
            if is_ru else
            ("If After Effects is installed in the default location — click\n"
             "“Default path”. Otherwise enter the path to the Plug-ins folder\n"
             "manually or via “Browse…”."),
            self,
        )
        desc.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        layout.addWidget(desc)

        # Поле пути + Обзор
        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_edit = QLineEdit(self)
        self.path_edit.setPlaceholderText(
            r"Например: C:\Program Files\Adobe\Adobe After Effects 2024\Support Files\Plug-ins"
            if is_ru else
            r"e.g. C:\Program Files\Adobe\Adobe After Effects 2024\Support Files\Plug-ins"
        )
        self.path_edit.textEdited.connect(self._on_path_edited)
        row.addWidget(self.path_edit, 1)

        self.btn_browse = QPushButton("Обзор…" if is_ru else "Browse…", self)
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse.clicked.connect(self._on_browse_clicked)
        row.addWidget(self.btn_browse)

        layout.addLayout(row)

        # Кнопка «Стандартный путь»
        self.btn_default = QPushButton(
            "Стандартный путь" if is_ru else "Default path", self
        )
        self.btn_default.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_default.clicked.connect(self._on_default_clicked)
        layout.addWidget(self.btn_default)

        # Подсказка под кнопкой со стандартным путём
        default_path = _detect_default_ae_path()
        if default_path:
            hint_text = (
                f"Найдено автоматически: {default_path}" if is_ru
                else f"Auto-detected: {default_path}"
            )
        else:
            hint_text = (
                "Стандартный Adobe-каталог не найден — введите путь вручную"
                if is_ru else
                "Default Adobe folder not found — enter the path manually"
            )
        self.lbl_hint = QLabel(hint_text, self)
        self.lbl_hint.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
        self.lbl_hint.setWordWrap(True)
        layout.addWidget(self.lbl_hint)

        # OK
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        ok_text = "Подтвердить" if is_ru else "Confirm"
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

        # Сразу проставим стандартный путь по умолчанию (если найден),
        # но пометим это как «используется стандартный».
        if default_path:
            self.path_edit.setText(default_path)
        self._use_default = True

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if sys.platform == "win32":
            QTimer.singleShot(10, lambda: apply_dark_titlebar(int(self.winId())))

    def _on_browse_clicked(self) -> None:
        is_ru = self._lang == "ru"
        start_dir = self.path_edit.text().strip() or os.environ.get(
            "ProgramFiles", r"C:\Program Files"
        )
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку Plug-ins" if is_ru else "Select the Plug-ins folder",
            start_dir,
        )
        if chosen:
            self.path_edit.setText(os.path.normpath(chosen))
            self._use_default = False
            self._update_hint_for_custom()

    def _on_default_clicked(self) -> None:
        is_ru = self._lang == "ru"
        default_path = _detect_default_ae_path()
        if default_path:
            self.path_edit.setText(default_path)
        else:
            self.path_edit.clear()
        self._use_default = True
        self.lbl_hint.setText(
            ("Будет использоваться стандартный путь "
             "(приложение определит его автоматически)") if is_ru else
            "The default path will be used (auto-detected at runtime)"
        )

    def _on_path_edited(self, _text: str) -> None:
        # Любая ручная правка переключает флаг на «кастомный путь»
        self._use_default = False
        self._update_hint_for_custom()

    def _update_hint_for_custom(self) -> None:
        is_ru = self._lang == "ru"
        self.lbl_hint.setText(
            "Будет использоваться указанный путь" if is_ru
            else "The entered path will be used"
        )

    def result_path(self) -> str:
        """
        Возвращает значение для записи в `custom_install_path`:
          • ""    — пользователь выбрал стандартный путь;
          • путь  — пользовательский путь.
        """
        if self._use_default:
            return ""
        text = self.path_edit.text().strip()
        return os.path.normpath(text) if text else ""


# ---------------------------------------------------------------------------
# Отдельное окно «Дополнительно»
# ---------------------------------------------------------------------------
class AdvancedWindow(QMainWindow):
    """
    Самостоятельное окно для AdvancedFrame. Создаётся лениво при первом
    клике на «Дополнительно» в главном окне. Закрытие просто прячет окно —
    повторный клик вернёт его без пересоздания.
    """

    def __init__(self, app_window: "AksiomInstaller") -> None:
        super().__init__(parent=None)  # отдельное верхнеуровневое окно
        self._app = app_window
        t = app_window.lang_dict.get(
            app_window.current_lang, app_window.lang_dict.get("en", {})
        )
        self.setWindowTitle(t.get("tab_advanced", "Дополнительно"))
        self.resize(1050, 720)
        self.setMinimumSize(820, 600)
        # Иконка приложения
        icon_path = getattr(app_window, "icon_path", "")
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def showEvent(self, event):  # noqa: N802 — Qt API
        super().showEvent(event)
        if sys.platform == "win32":
            QTimer.singleShot(0, lambda: apply_dark_titlebar(int(self.winId())))

    def closeEvent(self, event):  # noqa: N802 — Qt API
        # Прячем окно вместо разрушения — открыть снова дёшево.
        event.ignore()
        self.hide()


# ---------------------------------------------------------------------------
# Сигналы для обновлений из фоновых потоков
# ---------------------------------------------------------------------------
class UpdateSignals(QObject):
    """Прокидывает уведомления из threading-потоков в Qt-главный поток."""

    update_available = pyqtSignal(str)            # release_title
    db_updated = pyqtSignal()
    progress_updated = pyqtSignal(str, float)     # status_text, value (0..1)
    progress_value = pyqtSignal(float)            # только числовое значение (gdown)
    installation_finished = pyqtSignal(str)       # status_text


# ---------------------------------------------------------------------------
# Главный класс приложения
# ---------------------------------------------------------------------------
from installer_logic import InstallerLogicMixin
from plugin_checker import PluginCheckerMixin


class AksiomInstaller(InstallerLogicMixin, PluginCheckerMixin, QMainWindow):
    """Главное окно установщика плагинов After Effects."""

    # Дефолтные тексты языковых пакетов
    _DEFAULT_LANG: dict[str, dict[str, str]] = {
        "ru": {
            "title": "Ae plugins installer Beta 7.0",
            "version_lbl": "Выбор версии After Effects",
            "plugins_lbl": "Выбор плагинов",
            "select_all": "Выбрать все",
            "wait": "Ожидание...",
            "install_btn": "Установить выбранные",
            "log_lbl": "Журнал событий",
            "clear_log_btn": "Очистить логи",
            "export_log_btn": "Сохранить логи",
            "source_btn": "Источник",
            "complete": "Операция завершена",
            "tab_install": "Установка",
            "tab_advanced": "Дополнительно",
            "advanced_btn": "Дополнительно",
            "tab_changelog": "Список изменений",
            "tab_logs": "Логи",
            "tab_custom": "Свои плагины",
            "tab_settings": "Индивидуальные пути",
            "tab_sync": "Экспорт / Импорт",
            "tab_uninstall": "Удаление",
            "tab_options": "Прочее",
            "search_ph": "Поиск...",
            "force_install": "Принудительная установка",
            "warn_title": "Внимание",
            "exit_warn": "Установка не завершена. Выйти?",
        },
        "en": {
            "title": "Ae plugins Installer Beta 7.0",
            "version_lbl": "Select After Effects Version",
            "plugins_lbl": "Select Plugins",
            "select_all": "Select All",
            "wait": "Waiting...",
            "install_btn": "Install Selected",
            "log_lbl": "Event Log",
            "clear_log_btn": "Clear Logs",
            "export_log_btn": "Export Logs",
            "source_btn": "Source",
            "complete": "Operation Complete",
            "tab_install": "Installation",
            "tab_advanced": "Advanced",
            "advanced_btn": "Advanced",
            "tab_changelog": "Changelog",
            "tab_logs": "Logs",
            "tab_custom": "Custom Plugins",
            "tab_settings": "Individual Paths",
            "tab_sync": "Export / Import",
            "tab_uninstall": "Uninstall",
            "tab_options": "Misc",
            "search_ph": "Search...",
            "force_install": "Force Install",
            "warn_title": "Warning",
            "exit_warn": "Installation not finished. Exit?",
        },
    }

    CHANGELOG_TEXT: dict[str, str] = {
        "ru": (
            "Версия Beta 7.0:\n"
            "- Полный перенос на другую библиотеку\n"
            "- Ускорение UI\n"
            "- Улучшенная работа с путями\n"
            "- Улучшенная работа установки\n"
            "- Минорные обновления и баг фиксы\n\n"
            "Версия Beta 6.0:\n"
            "- Реворк раздела Конфигуратора своих плагинов\n"
            "- Установка более старых RSMB, Universe\n"
            "- Очистка кэша\n"
            "- Изменение работы с окнами\n"
            "- Добавление окна загрузки приложения\n"
            "- Минорные обновления и баг фиксы\n\n"
            "Версия Fake-Pre-release:\n"
            "- Кнопка принудительной установки\n"
            "- Раздел удаления\n"
            "- Поиск в меню\n"
            "- Минорные обновления и баг фиксы\n\n"
            "Версия Beta 5.0:\n"
            "- Добавление 26-ой версии АЕ в качестве эксперимента\n"
            "- Окно дополнительных настроек\n"
            "- Возможность добавления своих плагинов\n"
            "- Возможность изменения пути установки стандартных плагинов\n"
            "- Список изменений\n"
            "- Импорт и экспорт данных\n"
            "- Добавление версий и размера в списке плагинов\n"
            "- Улучшение работы с Google Drive\n"
            "- Добавление папки кэша\n"
            "- Исправление багов и минорные обновления\n"
        ),
        "en": (
            "Version Beta 7.0:\n"
            "- Full migration to a different library\n"
            "- UI speed-up\n"
            "- Improved path handling\n"
            "- Improved installation workflow\n"
            "- Minor updates and bug fixes\n\n"
            "Version Beta 6.0:\n"
            "- Reworked Custom Plugins Configurator section\n"
            "- Installing older RSMB, Universe\n"
            "- Clearing the cache\n"
            "- Changing window handling\n"
            "- Adding an application loading window\n"
            "- Minor updates and bug fixes\n\n"
            "Version Fake-Pre-release:\n"
            "- Force install button\n"
            "- Uninstall section\n"
            "- Menu search\n"
            "- Minor updates and bug fixes\n\n"
            "Version Beta 5.0:\n"
            "- Adding AE version 26 as an experiment\n"
            "- Additional settings window\n"
            "- Ability to add custom plugins\n"
            "- Ability to change standard plugins installation path\n"
            "- Changelog\n"
            "- Data import and export\n"
            "- Added versions and sizes to the plugins list\n"
            "- Improved Google Drive integration\n"
            "- Added cache folder\n"
            "- Bug fixes and minor updates\n"
        ),
    }

    # ------------------------------------------------------------------
    # Инициализация
    # ------------------------------------------------------------------
    def __init__(self, splash: "SplashDialog | None" = None) -> None:
        super().__init__()

        # 1. Сразу скрываем главное окно (показывается только после сплэша)
        self.hide()

        # 2. Сплэш. Если уже создан в main() и передан — используем его
        # (он отрисовался до начала тяжёлой инициализации). Иначе создаём
        # здесь — для обратной совместимости, если кто-то импортирует
        # AksiomInstaller напрямую.
        if splash is not None:
            self.splash = splash
        else:
            self.splash = SplashDialog()
            self.splash.show()
            QApplication.processEvents()  # принудительная отрисовка

        # 3. Базовые свойства окна
        self.setWindowTitle("Ae plugins installer Beta 7")
        self.resize(1050, 720)
        self.setMinimumSize(820, 600)

        # 4. Версия / URL
        self.CURRENT_VERSION: str = CURRENT_VERSION
        self.DB_URL: str = DB_URL

        # 5. Состояние UI и данных (вместо BooleanVar / StringVar)
        self.current_lang: str = self._detect_system_language()
        self.lang_dict: dict[str, dict[str, str]] = {}

        # данные плагинов
        self.plugins_data: list[tuple] = []
        self.plugin_keywords: dict[str, list[str]] = {}
        self.gdrive_file_ids: dict[str, str] = {}
        self.custom_data: dict[str, dict] = {}
        self.checkbox_widgets: dict[str, QWidget] = {}
        self.plugin_rows: dict[str, QWidget] = {}

        # лог
        self.log_history: list[dict[str, str]] = []
        # [AKSIOM-FIX #6] Ограничиваем рост — иначе при долгой работе течёт память.
        # deque c maxlen — drop-in для list.append/clear/индексации.
        self.persistent_log_history: deque[dict[str, str]] = deque(maxlen=10000)

        # настройки приложения (бывшие BooleanVar/StringVar)
        self.old_rsmb: bool = False
        self.rg_plugin_only: bool = True
        self.rg_maxon_app: bool = True
        # Old Red Giant mode — единая галочка, заменившая rg_plugin_only/rg_maxon_app
        # в UI. Когда False (по умолчанию), плагины Universe/Trapcode/MBS скрыты
        # из списка установки. Когда True — показываются.
        self.old_rg_mode: bool = False
        self.ae_drive: str = ""
        self.custom_install_path: str = ""
        self.force_install: bool = False
        self.selected_ae_version: str = "None"
        self.search_text: str = ""
        self.custom_plugin_paths: dict[str, str] = {}
        self.install_in_progress: bool = False

        # сигналы для безопасного обновления UI из потоков
        self.signals = UpdateSignals()
        self.signals.update_available.connect(self.show_update_button)
        self.signals.progress_updated.connect(self._on_progress_updated)
        self.signals.progress_value.connect(self._on_progress_value)
        self.signals.installation_finished.connect(self._on_installation_finished)

        # 6. Пути и каталоги
        if getattr(sys, "frozen", False):
            self.app_dir = os.path.dirname(sys.executable)
            bundle_dir = sys._MEIPASS  # type: ignore[attr-defined]
        else:
            self.app_dir = os.path.dirname(os.path.abspath(__file__))
            bundle_dir = self.app_dir

        self.cache_dir = os.path.join(self.app_dir, "Aksiom-installer-cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.base_dir = self.cache_dir

        self.custom_configs_dir = os.path.join(self.base_dir, "custom_configs")
        os.makedirs(self.custom_configs_dir, exist_ok=True)

        # Миграция со старого формата хранения
        old_custom_db = os.path.join(self.base_dir, "custom_plugins.json")
        if os.path.exists(old_custom_db):
            try:
                shutil.move(
                    old_custom_db,
                    os.path.join(self.custom_configs_dir, "custom_plugins.json"),
                )
            except OSError as exc:
                print(f"Migration of custom_plugins.json failed: {exc}")

        self.app_config_file = os.path.join(self.base_dir, "app_config.json")
        self.settings_file = os.path.join(self.base_dir, "settings.json")

        # Иконка приложения
        self.icon_path = os.path.join(bundle_dir, "logo.ico")
        if os.path.exists(self.icon_path):
            self.setWindowIcon(QIcon(self.icon_path))

        # 7. Загрузка конфигов
        self.app_settings = self.load_app_config()
        self.old_rsmb = self.app_settings.get("old_rsmb", False)
        self.rg_plugin_only = self.app_settings.get("rg_plugin_only", True)
        self.rg_maxon_app = self.app_settings.get("rg_maxon_app", True)
        self.old_rg_mode = self.app_settings.get("old_rg_mode", False)
        self.ae_drive = self.app_settings.get("ae_drive", "")
        # Кастомный путь к After Effects (полный путь к папке Plug-ins).
        # Пустая строка означает «использовать стандартный путь».
        self.custom_install_path = self.app_settings.get("custom_install_path", "")

        self.lang_dict = self.load_language_file()
        self.custom_plugin_paths = self.load_settings()

        # 8. Загрузка БД плагинов
        self.load_plugins_database()

        # 9. UI
        self.create_main_tabs()

        # 10. Финальные действия — проверку обновлений запускаем ПОСЛЕ
        # показа окна, чтобы не задерживать старт сетевым потоком.
        # [AKSIOM-FIX 2026-05] Раньше check_for_updates() вызывался прямо
        # в __init__ (создаёт threading.Thread — недорого, но всё равно
        # выполняется до отрисовки UI). Теперь — через QTimer после showEvent.

        # 11. Закрытие сплэша — без искусственной задержки.
        # [AKSIOM-FIX 2026-05] Раньше тут было QTimer.singleShot(200, ...),
        # что добавляло ~200мс к ощущаемому времени старта на ровном месте.
        QTimer.singleShot(0, self._close_splash_and_show)

    # ------------------------------------------------------------------
    # Сплэш / показ окна
    # ------------------------------------------------------------------
    def _close_splash_and_show(self) -> None:
        """Закрывает сплэш и показывает основное окно."""
        try:
            self.splash.close()
            self.splash.deleteLater()
        except Exception as exc:  # noqa: BLE001
            print(f"Splash close error: {exc}")

        # Закрытие splash от PyInstaller (если есть)
        try:
            import pyi_splash  # type: ignore
            pyi_splash.close()
        except ImportError:
            pass

        self.show()
        # Тёмный тайтлбар главного окна
        if sys.platform == "win32":
            QTimer.singleShot(0, lambda: apply_dark_titlebar(int(self.winId())))

        # [AKSIOM-FIX 2026-05] Проверку обновлений GitHub запускаем здесь,
        # уже после показа главного окна. Сам HTTP-запрос идёт в фоновом
        # потоке, но создание потока вынесено сюда, чтобы старт UI не
        # замедлялся даже на миллисекунды.
        QTimer.singleShot(500, self.check_for_updates)

        # Первый запуск — спросить путь к AE.
        # Запускаем после небольшой задержки, чтобы главное окно успело
        # отрисоваться и стало родителем для модального диалога.
        QTimer.singleShot(120, self._maybe_ask_first_run_path)

    # ------------------------------------------------------------------
    # Первый запуск: запрос пути к After Effects
    # ------------------------------------------------------------------
    def _maybe_ask_first_run_path(self) -> None:
        """
        Если путь к AE ещё не настраивался (первый запуск приложения) —
        показывает FirstRunPathDialog и сохраняет результат в конфиг.
        """
        if self.app_settings.get("ae_path_configured"):
            return

        dlg = FirstRunPathDialog(self.current_lang, parent=self)
        dlg.exec()  # модально

        chosen = dlg.result_path()
        # Пустая строка = «стандартный путь» (логика установки/удаления
        # уже умеет это: при пустом custom_install_path путь вычисляется
        # автоматически из ProgramFiles + версии AE).
        self.custom_install_path = chosen
        self.app_settings["custom_install_path"] = chosen
        self.app_settings["ae_path_configured"] = True
        self.save_app_config()

        # Перепроверим установленные плагины с учётом нового пути,
        # если соответствующая вкладка уже создана.
        install_tab = getattr(self, "install_tab_widget", None)
        if install_tab is not None and hasattr(install_tab, "check_installed_plugins"):
            try:
                install_tab.check_installed_plugins()
            except Exception as exc:  # noqa: BLE001
                print(f"check_installed_plugins after first-run: {exc}")

    # ------------------------------------------------------------------
    # Язык
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_system_language() -> str:
        """Определяет системный язык. RU при русской локали Windows, иначе EN."""
        try:
            if sys.platform == "win32":
                lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
                sys_lang = locale.windows_locale.get(lang_id, "en")
            else:
                sys_lang = (locale.getdefaultlocale()[0] or "en").lower()
            return "ru" if sys_lang.lower().startswith("ru") else "en"
        except Exception:  # noqa: BLE001
            return "en"

    def load_language_file(self) -> dict[str, dict[str, str]]:
        """Читает lang.json из cache_dir, при отсутствии — создаёт со значениями по умолчанию.

        [AKSIOM-FIX 2026-05] Файл перезаписываем только если содержимое
        реально изменилось (или файла нет). Раньше перезапись делалась
        безусловно на каждый запуск — лишний disk I/O при старте.
        """
        lang_path = os.path.join(self.base_dir, "lang.json")
        # Глубокая копия дефолтов
        current = {k: dict(v) for k, v in self._DEFAULT_LANG.items()}

        file_existed = os.path.exists(lang_path)
        loaded_raw = None
        if file_existed:
            try:
                with open(lang_path, "r", encoding="utf-8") as f:
                    loaded_raw = json.load(f)
                if isinstance(loaded_raw, dict):
                    for lang in ("ru", "en"):
                        if lang in loaded_raw:
                            current[lang].update(loaded_raw[lang])
            except json.JSONDecodeError as exc:
                print(f"Failed to load language json: {exc}")
            except OSError as exc:
                print(f"Error accessing lang.json: {exc}")

        # Пишем только если файла нет ИЛИ контент после merge отличается.
        needs_write = (not file_existed) or (loaded_raw != current)
        if needs_write:
            try:
                with open(lang_path, "w", encoding="utf-8") as f:
                    json.dump(current, f, ensure_ascii=False, indent=4)
            except OSError as exc:
                print(f"Error writing to lang.json: {exc}")

        return current

    # ------------------------------------------------------------------
    # Конфиги
    # ------------------------------------------------------------------
    def load_app_config(self) -> dict:
        if os.path.exists(self.app_config_file):
            try:
                with open(self.app_config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"load_app_config: {exc}")
        return {}

    def save_app_config(self) -> None:
        self.app_settings["old_rsmb"] = self.old_rsmb
        self.app_settings["rg_plugin_only"] = self.rg_plugin_only
        self.app_settings["rg_maxon_app"] = self.rg_maxon_app
        self.app_settings["old_rg_mode"] = self.old_rg_mode
        self.app_settings["ae_drive"] = self.ae_drive
        self.app_settings["custom_install_path"] = self.custom_install_path
        try:
            with open(self.app_config_file, "w", encoding="utf-8") as f:
                json.dump(self.app_settings, f, ensure_ascii=False)
        except OSError as exc:
            print(f"save_app_config: {exc}")

    def load_settings(self) -> dict[str, str]:
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError as exc:
                print(f"Error reading settings: {exc}")
            except OSError as exc:
                print(f"OS Error loading settings: {exc}")
        return {}

    def save_settings(self) -> None:
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.custom_plugin_paths, f, ensure_ascii=False, indent=4)
        except OSError as exc:
            print(f"Error saving settings: {exc}")

    # ------------------------------------------------------------------
    # БД плагинов
    # ------------------------------------------------------------------
    def load_plugins_database(self) -> None:
        """Грузит plugins.json (локально → сеть в фоне).

        После загрузки данных — независимо от источника — применяет
        _merge_old_rg_plugins, чтобы Universe/Trapcode/MBS гарантированно
        присутствовали в списке (даже если их нет в скачанном файле).
        """
        local_db_path = os.path.join(self.base_dir, "plugins.json")
        data = None

        if os.path.exists(local_db_path):
            try:
                with open(local_db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"Error loading local plugins.json: {exc}")

        if data:
            # Локальные данные есть — мерджим, парсим, и сохраняем мерджнутую
            # версию обратно на диск ТОЛЬКО если merge что-то добавил
            # (чтобы не делать лишний disk I/O при каждом запуске).
            # [AKSIOM-FIX 2026-05] Раньше perистил безусловно.
            plugins_before = len(data.get("plugins", []) or [])
            data = _merge_old_rg_plugins(data)
            plugins_after = len(data.get("plugins", []) or [])
            if plugins_after != plugins_before:
                try:
                    self._atomic_write_json(local_db_path, data)
                except OSError as exc:
                    print(f"Failed to persist merged plugins.json: {exc}")
            self._parse_plugins_data(data)
            threading.Thread(
                target=self._update_db_in_background,
                args=(local_db_path,),
                daemon=True,
            ).start()
            return

        # Локальных данных нет — пробуем синхронно скачать.
        try:
            req = urllib.request.Request(
                self.DB_URL, headers={"User-Agent": "AksiomInstaller"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
            data = _merge_old_rg_plugins(data)
            self._atomic_write_json(local_db_path, data)
        except Exception as exc:  # noqa: BLE001
            # Сеть недоступна — попробуем хотя бы стартовать с одним только
            # фолбэком (Universe/Trapcode/MBS), чтобы UI не падал. Без них
            # пользователь увидит «пустой» список плагинов, что лучше чем
            # SystemExit.
            print(f"DB download failed: {exc}")
            data = _merge_old_rg_plugins({"plugins": []})
            try:
                self._atomic_write_json(local_db_path, data)
            except OSError as exc2:
                print(f"Failed to write fallback plugins.json: {exc2}")

        self._parse_plugins_data(data)

    @staticmethod
    def _atomic_write_json(path: str, data: object) -> None:
        """Записывает JSON атомарно через .tmp + os.replace, чтобы не оставить
        битый файл при сбое в момент записи."""
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(tmp, path)
        finally:
            # На случай если os.replace упал — почистим .tmp
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def _update_db_in_background(self, local_db_path: str) -> None:
        try:
            req = urllib.request.Request(
                self.DB_URL, headers={"User-Agent": "AksiomInstaller"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                new_data = json.loads(response.read().decode("utf-8"))
            # Защита от потери Universe/Trapcode/MBS: всегда мерджим перед записью.
            new_data = _merge_old_rg_plugins(new_data)
            self._atomic_write_json(local_db_path, new_data)
            self.signals.db_updated.emit()
        except Exception as exc:  # noqa: BLE001
            print(f"Background DB update failed: {exc}")

    def _parse_plugins_data(self, data: dict | None) -> None:
        """Заполняет self.plugins_data, plugin_keywords, gdrive_file_ids, custom_data."""
        if data and "plugins" in data:
            for p in data["plugins"]:
                name = p["name"]
                self.plugins_data.append(
                    (
                        name,
                        p.get("version", "1.0"),
                        p.get("bat_path", ""),
                        p.get("needs_version", False),
                        p.get("size", ""),
                        p.get("md5"),
                    )
                )

                base_kw = name.lower()
                default_kws = [
                    base_kw.replace("_", " ").strip(),
                    base_kw,
                    base_kw.replace("_", ""),
                ]
                if name == "RedGiant":
                    # Trapcode и Magic Bullet теперь — отдельные плагины
                    # (см. plugins.json: Trapcode, MBS), поэтому из ключей
                    # RedGiant их убрали, чтобы не было ложного срабатывания
                    # детектора установки.
                    default_kws.extend(
                        ["red giant", "vfx", "pluraleyes", "colorista"]
                    )
                elif name == "Universe":
                    default_kws.extend(["red giant universe", "universe"])
                elif name == "Trapcode":
                    default_kws.extend(["trapcode", "particular", "form"])
                elif name == "MBS":
                    default_kws.extend(["magic bullet", "magic bullet suite", "mbs"])

                json_kws = list(p.get("keywords", []))
                if name == "RedGiant" and "red giant" in json_kws:
                    json_kws.remove("red giant")

                # [AKSIOM-FIX #24] dict.fromkeys сохраняет порядок (Python 3.7+)
                self.plugin_keywords[name] = list(dict.fromkeys(default_kws + json_kws))
                self.gdrive_file_ids[name] = p.get("gdrive_id", "")

        # [AKSIOM-FIX #18] Парсинг custom-плагинов вынесен в helper
        self._load_custom_plugins_from_dir()

    def _load_custom_plugins_from_dir(self) -> None:
        """[AKSIOM-FIX #18] Единая точка парсинга custom-плагинов.
        Вызывается из _parse_plugins_data и reload_custom_plugins."""
        if not os.path.exists(self.custom_configs_dir):
            return
        for filename in os.listdir(self.custom_configs_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(self.custom_configs_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    c_data = json.load(f)
                for p in c_data.get("plugins", []):
                    name = p["name"]
                    self.plugins_data.append(
                        (
                            name,
                            p.get("version", "1.0"),
                            "CUSTOM",
                            False,
                            p.get("size", ""),
                            None,
                        )
                    )

                    base_kw = name.lower()
                    default_kws = [
                        base_kw.replace("_", " ").strip(),
                        base_kw,
                        base_kw.replace("_", ""),
                    ]
                    json_kws = list(p.get("keywords", []))
                    # [AKSIOM-FIX #24] Сохраняем порядок ключевых слов
                    self.plugin_keywords[name] = list(dict.fromkeys(default_kws + json_kws))
                    self.gdrive_file_ids[name] = p.get("gdrive_id", "")
                    self.custom_data[name] = p
            except (OSError, json.JSONDecodeError) as exc:
                print(f"Error parsing {filename}: {exc}")

    # ------------------------------------------------------------------
    # Утилиты работы с плагинами (отображение, проверка установки)
    # ------------------------------------------------------------------
    def get_plugin_display_text(
        self, plugin_name: str, version: str, bat_path: str, size: str
    ) -> str:
        """Аналог оригинального get_plugin_display_text."""
        prefix = "★ " if bat_path == "CUSTOM" else ""
        ver_text = "" if version == "1.0" else f" [v{version}]"
        suffix = ""
        if plugin_name == "RSMB" and getattr(self, "old_rsmb", False):
            suffix += " [Old]"
        # Маркер старого Red Giant режима для трёх «новых» плагинов.
        # Видны они только когда old_rg_mode == True (фильтр в install_tab),
        # но и в самой подписи отметим [Old], чтобы пользователь не путал
        # их с актуальным RedGiant.
        if plugin_name in ("Universe", "Trapcode", "MBS"):
            suffix += " [Old]"
        return f"{prefix}{plugin_name}{ver_text}  ({size}){suffix}"

    def update_all_plugin_labels(self) -> None:
        """Обновляет тексты всех чекбоксов плагинов (после смены настроек/языка)."""
        widget = getattr(self, "install_tab_widget", None)
        if widget is None:
            return
        for plugin_data in self.plugins_data:
            name, ver, bat, _, size, _ = plugin_data
            cb = widget.checkbox_widgets.get(name)
            if cb is not None:
                cb.setText(self.get_plugin_display_text(name, ver, bat, size))

    # is_plugin_installed: override в InstallerLogicMixin → идёт через
    # PluginPipeline (манифесты + detect + legacy fallback в PluginCheckerMixin).

    def reload_custom_plugins(self) -> None:
        """
        Перезагружает custom-плагины с диска и пересобирает их строки в UI.
        Вызывается после сохранения/удаления custom-плагина.
        """
        # Удаляем все плагины с bat_path == "CUSTOM" из общего списка
        non_custom = [p for p in self.plugins_data if p[2] != "CUSTOM"]
        custom_names = {p[0] for p in self.plugins_data if p[2] == "CUSTOM"}

        # Чистим связанные хранилища
        for cname in custom_names:
            self.plugin_keywords.pop(cname, None)
            self.gdrive_file_ids.pop(cname, None)
        self.custom_data.clear()
        self.plugins_data = non_custom

        # [AKSIOM-FIX #18] Перечитываем custom_configs через общий helper
        self._load_custom_plugins_from_dir()

        # Перестраиваем UI установки: удалить старые строки CUSTOM и добавить новые
        widget = getattr(self, "install_tab_widget", None)
        if widget is not None:
            # удалить из layout все строки custom-плагинов
            for cname in list(custom_names):
                row = widget.plugin_rows.pop(cname, None)
                widget.checkbox_widgets.pop(cname, None)
                widget.checkboxes = [(n, c) for n, c in widget.checkboxes if n != cname]
                if row is not None:
                    row.setParent(None)
                    row.deleteLater()
            # добавить новые
            for p in self.plugins_data:
                name, ver, bat, _, size, _ = p
                if bat == "CUSTOM" and name not in widget.checkbox_widgets:
                    widget.add_plugin_row(name, ver, bat, size)

    # ------------------------------------------------------------------
    # Слоты сигналов установки (вызываются из главного потока)
    # ------------------------------------------------------------------
    def _on_progress_updated(self, text: str, value: float) -> None:
        widget = getattr(self, "install_tab_widget", None)
        if widget is None:
            return
        widget.progress_label.setText(text)
        widget.progressbar.setValue(int(value * 1000))

    def _on_progress_value(self, value: float) -> None:
        """Только числовое значение прогресса (от GdownLogCatcher)."""
        widget = getattr(self, "install_tab_widget", None)
        if widget is None:
            return
        widget.progressbar.setValue(int(value * 1000))

    def _on_installation_finished(self, status_text: str) -> None:
        """Финализация после run_install_process — разблокировка UI."""
        self.install_in_progress = False
        widget = getattr(self, "install_tab_widget", None)
        if widget is None:
            return
        widget.progress_label.setText(status_text)
        widget.progressbar.setValue(1000)
        widget.btn_install.setEnabled(True)
        # перепроверка установленных плагинов
        widget.check_installed_plugins()


    def create_main_tabs(self) -> None:
        """
        Собирает корневой виджет:
            QVBoxLayout
                ├── QStackedWidget (Установка / Дополнительно)
                └── QHBoxLayout (футер: ссылки слева, переключатель + clear справа)
        """
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])

        central = QWidget(self)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        # ----- верхняя часть: QStackedWidget содержит только вкладку Установки.
        # «Дополнительно» открывается отдельным окном (см. open_advanced_window).
        self.stack = QStackedWidget(central)

        # Импорт здесь, чтобы избежать циклических зависимостей при старте модуля
        from install_tab import InstallTab

        self.install_tab_widget = InstallTab(self, parent=central)

        # Старые имена сохраняем как алиасы
        self.install_frame = self.install_tab_widget

        self.stack.addWidget(self.install_frame)   # index 0
        self.stack.setCurrentIndex(0)

        # Окно «Дополнительно» создаётся лениво при первом открытии.
        self.advanced_window: "AdvancedWindow | None" = None
        self.advanced_frame_widget = None  # будет создано при открытии окна
        self.advanced_frame = None         # алиас для обратной совместимости

        root.addWidget(self.stack, stretch=1)

        # ----- нижняя часть: глобальный футер -----
        footer = QWidget(central)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(10)

        # Слева — ссылки
        links = QWidget(footer)
        links_layout = QHBoxLayout(links)
        links_layout.setContentsMargins(0, 0, 0, 0)
        links_layout.setSpacing(10)

        for text, url in (
            ("GitHub", "https://github.com/Aks-iom/Aks-iom-AE-Plugins-install-script"),
            ("Telegram", "https://t.me/AE_plugins_script"),
            (t.get("source_btn", "Source"), "https://satvrn.li/windows"),
        ):
            btn = QPushButton(text, links)
            btn.setObjectName("LinkButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, u=url: webbrowser.open(u))
            links_layout.addWidget(btn)

        footer_layout.addWidget(links, alignment=Qt.AlignmentFlag.AlignLeft)
        footer_layout.addStretch(1)

        # Справа — кнопка «Дополнительно» (открывает отдельное окно) + Очистить лог
        self.btn_advanced = QPushButton(
            t.get("tab_advanced", "Дополнительно"), footer
        )
        self.btn_advanced.setObjectName("DarkButton")
        self.btn_advanced.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_advanced.clicked.connect(self.open_advanced_window)
        footer_layout.addWidget(self.btn_advanced)

        self.btn_clear_log = QPushButton(t.get("clear_log_btn", "Clear"), footer)
        self.btn_clear_log.setObjectName("DarkButton")
        self.btn_clear_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_log.clicked.connect(self.clear_logs)
        footer_layout.addWidget(self.btn_clear_log)

        root.addWidget(footer)

        # Слот для будущей кнопки обновления (в правом верхнем углу install_frame)
        self.btn_update: QPushButton | None = None

    # ------------------------------------------------------------------
    # «Дополнительно» — отдельное окно
    # ------------------------------------------------------------------
    def open_advanced_window(self) -> None:
        """
        Открывает (или поднимает наверх, если уже открыто) отдельное окно
        «Дополнительно» с виджетом AdvancedFrame внутри.

        Если окно уже видимо — повторный клик по кнопке должен поставить его
        ПОВЕРХ главного. На Windows одного raise_()+activateWindow() часто
        недостаточно (ОС блокирует «кражу фокуса» у не-foreground процесса),
        поэтому используем временный WindowStaysOnTopHint, который снимаем
        сразу после показа: окно всплывает гарантированно, но не остаётся
        в режиме "always on top".
        """
        if self.advanced_window is None:
            from advanced_frame import AdvancedFrame
            self.advanced_window = AdvancedWindow(self)
            self.advanced_frame_widget = AdvancedFrame(
                self, parent=self.advanced_window
            )
            self.advanced_frame = self.advanced_frame_widget
            self.advanced_window.setCentralWidget(self.advanced_frame_widget)

        win = self.advanced_window
        was_visible = win.isVisible()

        if not was_visible:
            win.show()
        else:
            # Окно уже открыто. Принудительно поднимаем поверх главного.
            # 1) Временно ставим WindowStaysOnTopHint, перепоказываем (флаги
            #    меняются только при перерисовке окна, поэтому show() обязателен).
            # 2) Сразу снимаем флаг и снова перепоказываем — окно остаётся
            #    наверху своего Z-стэка, но не "пришпилено" навсегда.
            win.setWindowState(
                (win.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
            flags = win.windowFlags()
            win.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
            win.show()
            win.setWindowFlags(flags)
            win.show()

        win.raise_()
        win.activateWindow()

    def switch_main_view(self, selected_view: str) -> None:
        """
        Совместимость: раньше переключал между Установка/Дополнительно,
        теперь Дополнительно живёт в отдельном окне. Метод оставлен на случай
        вызовов из других мест — он просто открывает окно «Дополнительно»,
        если выбрано «Дополнительно».
        """
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
        if selected_view == t.get("tab_advanced", "Дополнительно"):
            self.open_advanced_window()

    def _reposition_view_switcher_underline(self) -> None:
        """No-op: переключатель удалён, метод оставлен для совместимости."""
        return

    def resizeEvent(self, event):  # noqa: N802 — Qt API
        super().resizeEvent(event)

    # ------------------------------------------------------------------
    # Язык: переключение и обновление надписей
    # ------------------------------------------------------------------
    def toggle_language(self) -> None:
        """Переключает RU↔EN и обновляет тексты UI."""
        self.current_lang = "en" if self.current_lang == "ru" else "ru"
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])

        # Кнопка «Дополнительно» в футере
        if hasattr(self, "btn_advanced") and self.btn_advanced is not None:
            self.btn_advanced.setText(t.get("tab_advanced", "Дополнительно"))

        # Тайтл и общие подписи
        self.setWindowTitle(t.get("title", self.windowTitle()))

        if hasattr(self, "btn_clear_log"):
            self.btn_clear_log.setText(t.get("clear_log_btn", "Clear"))

        # Кнопка обновления
        if self.btn_update is not None and hasattr(self, "update_btn_texts"):
            self.btn_update.setText(self.update_btn_texts[self.current_lang])

        # Ретрансляция содержимого вкладок
        widget = getattr(self, "install_tab_widget", None)
        if widget is not None and hasattr(widget, "retranslate"):
            widget.retranslate()
        adv = getattr(self, "advanced_frame_widget", None)
        if adv is not None and hasattr(adv, "retranslate"):
            adv.retranslate()

        # Заголовок отдельного окна «Дополнительно», если оно открыто
        if self.advanced_window is not None:
            self.advanced_window.setWindowTitle(
                t.get("tab_advanced", "Дополнительно")
            )

    # ------------------------------------------------------------------
    # Логи (делегируем InstallTab; работают и до создания вкладки)
    # ------------------------------------------------------------------
    def log(self, ru_text: str, en_text: str | None = None) -> None:
        """Потокобезопасное логирование. Делегирует InstallTab.log."""
        if en_text is None:
            en_text = ru_text
        widget = getattr(self, "install_tab_widget", None)
        if widget is not None:
            widget.log(ru_text, en_text)
        else:
            # На случай вызова до создания UI — просто пишем в историю
            self.log_history.append({"ru": ru_text, "en": en_text})
            self.persistent_log_history.append({"ru": ru_text, "en": en_text})

    def _update_last_log_line(
        self, ru_text: str, en_text: str | None = None
    ) -> None:
        """Перезапись последней строки лога (для прогресса gdown)."""
        widget = getattr(self, "install_tab_widget", None)
        if widget is not None:
            widget._update_last_log_line(ru_text, en_text)

    def clear_logs(self) -> None:
        """Очищает текстовое поле логов и историю."""
        self.log_history.clear()
        # [AKSIOM-FIX #6] Чистим и persistent — оставлять смысла мало
        self.persistent_log_history.clear()
        widget = getattr(self, "install_tab_widget", None)
        if widget is not None and hasattr(widget, "log_textbox"):
            widget.log_textbox.clear()
        adv = getattr(self, "advanced_frame_widget", None)
        if adv is not None and hasattr(adv, "adv_log_textbox"):
            adv.adv_log_textbox.clear()

    # ------------------------------------------------------------------
    # Проверка обновлений
    # ------------------------------------------------------------------
    def check_for_updates(self) -> None:
        """Запускает проверку версии в фоне; через сигнал зовёт show_update_button."""

        def fetch() -> None:
            try:
                req = urllib.request.Request(
                    RELEASES_URL, headers={"User-Agent": "AksiomInstaller"}
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode())
                release_name = data.get("name", "") or data.get("tag_name", "")
                if self._is_version_newer(release_name, self.CURRENT_VERSION):
                    title = self._extract_display_version(release_name)
                    self.signals.update_available.emit(title)
            except Exception as exc:  # noqa: BLE001
                print(f"Update check failed: {exc}")

        threading.Thread(target=fetch, daemon=True).start()

    @staticmethod
    def _extract_version_number(text: str) -> str:
        import re
        match = re.search(r"\d+(\.\d+)*", text.replace(",", "."))
        return match.group() if match else "0.0"

    @classmethod
    def _extract_display_version(cls, text: str) -> str:
        import re
        match = re.search(r"(?:Beta\s*)?\d+(?:[.,]\d+)*", text, re.IGNORECASE)
        if match:
            found = match.group()
            return (
                "V.Beta " + found[4:].strip()
                if found.lower().startswith("beta")
                else "V." + found
            )
        return text

    @classmethod
    def _is_version_newer(cls, latest: str, current: str) -> bool:
        """Сравнение версий вида 'Beta 6.0' / 'V.6.1'. True если latest > current."""
        try:
            v_latest = tuple(map(int, cls._extract_version_number(latest).split(".")))
            v_current = tuple(map(int, cls._extract_version_number(current).split(".")))
            length = max(len(v_latest), len(v_current))
            return (
                v_latest + (0,) * (length - len(v_latest))
                > v_current + (0,) * (length - len(v_current))
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Version compare error: {exc}")
            return False

    def show_update_button(self, release_title: str) -> None:
        """Создаёт кнопку «Скачать обновление» и встраивает её в правый верх install_frame."""
        self.update_btn_texts = {
            "ru": f"Скачать обновление ({release_title})",
            "en": f"Download update ({release_title})",
        }
        widget = getattr(self, "install_tab_widget", None)
        parent = widget.update_btn_container if widget is not None else self
        self.btn_update = QPushButton(self.update_btn_texts[self.current_lang], parent)
        self.btn_update.setStyleSheet(
            f"background-color: {COLOR_ACCENT}; color: white; "
            f"border-radius: 6px; padding: 6px 12px; font-weight: bold;"
        )
        self.btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_update.clicked.connect(
            lambda: webbrowser.open(
                "https://github.com/Aks-iom/Aks-iom-AE-Plugins-install-script/releases/tag/AE"
            )
        )
        # Если контейнер из InstallTab доступен — добавить туда
        if widget is not None and hasattr(widget, "update_btn_container"):
            layout = widget.update_btn_container.layout()
            if layout is not None:
                layout.addWidget(self.btn_update)

    # ------------------------------------------------------------------
    # Горячие клавиши русской раскладки (Ctrl+A/C/V/X/Z по keyCode)
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — Qt API
        """
        Аналог _fix_russian_hotkeys: ловим Ctrl+<keycode> по физической клавише,
        чтобы Ctrl+Ф/С/М/Ч/Я работали как Ctrl+A/C/V/X/Z.
        Использует event.nativeVirtualKey(), который не зависит от раскладки.
        """
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            vk = event.nativeVirtualKey()
            # Виртуальные коды Windows совпадают с ASCII заглавными
            mapping = {
                0x41: Qt.Key.Key_A,
                0x43: Qt.Key.Key_C,
                0x56: Qt.Key.Key_V,
                0x58: Qt.Key.Key_X,
                0x5A: Qt.Key.Key_Z,
            }
            if vk in mapping:
                target_key = mapping[vk]
                widget = QApplication.focusWidget()
                if widget is not None:
                    # Перенаправляем как «настоящее» сочетание на латинице
                    new_event = QKeyEvent(
                        event.type(),
                        target_key,
                        event.modifiers(),
                        "",  # text
                        event.isAutoRepeat(),
                        event.count(),
                    )
                    QApplication.sendEvent(widget, new_event)
                    event.accept()
                    return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Закрытие окна
    # ------------------------------------------------------------------
    def on_closing(self) -> bool:
        """Возвращает True если можно закрывать окно, иначе False."""
        installing = getattr(self, "install_in_progress", False)
        if installing:
            t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
            reply = QMessageBox.question(
                self,
                t.get("warn_title", "Warning"),
                t.get("exit_warn", "Installation not finished. Exit?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        if not self.on_closing():
            event.ignore()
            return
        # Корректное завершение через QApplication.quit() —
        # позволяет Qt отправить afterClosing-события и сохранить состояние.
        # os._exit(0) не дёргается специально: все наши threading-потоки
        # помечены daemon=True и сами умрут с процессом.
        event.accept()
        try:
            QApplication.quit()
        except Exception:
            # На самый край — если Qt по какой-то причине отказывается
            # завершаться (зависшие нативные вызовы), форсируем выход.
            os._exit(0)


# ---------------------------------------------------------------------------
# UAC-эскалация
# ---------------------------------------------------------------------------
def is_admin() -> bool:
    """Проверяет, запущено ли приложение с правами администратора."""
    try:
        if sys.platform == "win32":
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


def relaunch_as_admin() -> None:
    """Перезапускает приложение с правами администратора через Windows UAC."""
    if sys.platform != "win32":
        return
    params = (
        " ".join(f'"{arg}"' for arg in sys.argv[1:])
        if getattr(sys, "frozen", False)
        else f'"{os.path.abspath(__file__)}" '
        + " ".join(f'"{arg}"' for arg in sys.argv[1:])
    )
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1
    )
