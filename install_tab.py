# -*- coding: utf-8 -*-
"""
install_tab.py
Вкладка «Установка» — основной экран приложения.
Содержит: выбор версии AE, список плагинов с поиском, прогрессбар, кнопку
установки, лог событий справа, переключатель языка.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PyQt6.QtCore import (
    QEvent,
    QObject,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from styles import (
    CHECKMARK_DATA_URL,
    COLOR_ACCENT,
    COLOR_ACCENT_HOV,
    COLOR_BORDER,
    COLOR_CARD,
    COLOR_CUSTOM,
    COLOR_CUSTOM_HOV,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
    SegmentedButton,
)

if TYPE_CHECKING:
    from main_window import AksiomInstaller


# ---------------------------------------------------------------------------
# Сигналы для безопасного обновления UI из фоновых потоков
# ---------------------------------------------------------------------------
class InstallTabSignals(QObject):
    """Прокидывает обновления из threading.Thread в главный Qt-поток."""

    log_added = pyqtSignal(str, str)               # ru_text, en_text
    last_log_updated = pyqtSignal(str, str)        # ru_text, en_text
    installed_check_done = pyqtSignal(dict)        # {plugin_name: bool}
    progress_updated = pyqtSignal(str, float)      # status_text, value (0..1)


# ---------------------------------------------------------------------------
# Виджет с плавным колесом мыши (для скролл-листа плагинов)
# ---------------------------------------------------------------------------
class SmoothScrollArea(QScrollArea):
    """QScrollArea с покадровой анимацией прокрутки колесом мыши."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._target_value: int | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 fps
        self._timer.timeout.connect(self._tick)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        bar = self.verticalScrollBar()
        if bar.minimum() == bar.maximum():
            event.ignore()
            return

        # Шаг прокрутки — 6% от диапазона на каждый "тик" колеса
        step = max(20, int((bar.maximum() - bar.minimum()) * 0.06))
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return

        direction = -1 if delta > 0 else 1
        base = self._target_value if self._target_value is not None else bar.value()
        self._target_value = max(bar.minimum(), min(bar.maximum(), base + direction * step))

        if not self._timer.isActive():
            self._timer.start()
        event.accept()

    def _tick(self) -> None:
        if self._target_value is None:
            self._timer.stop()
            return
        bar = self.verticalScrollBar()
        current = bar.value()
        diff = self._target_value - current
        if abs(diff) <= 1:
            bar.setValue(self._target_value)
            self._target_value = None
            self._timer.stop()
        else:
            bar.setValue(current + int(diff * 0.25))


# ---------------------------------------------------------------------------
# InstallTab — основная вкладка
# ---------------------------------------------------------------------------
class InstallTab(QWidget):
    """Вкладка «Установка» — слева список плагинов, справа лог."""

    AE_VERSIONS = ["None", "20", "21", "22", "23", "24", "25", "26"]

    def __init__(self, app: "AksiomInstaller", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.signals = InstallTabSignals()

        # --- хранилища UI и состояния плагинов ---
        # checkboxes: список (name, QCheckBox) — порядок важен (так же, как в оригинале)
        self.checkboxes: list[tuple[str, QCheckBox]] = []
        # для совместимости с main_window: dict name -> QCheckBox (бывший checkbox_widgets)
        self.checkbox_widgets: dict[str, QCheckBox] = {}
        # row-обёртки чекбоксов (для скрытия при поиске)
        self.plugin_rows: dict[str, QWidget] = {}

        self._building_select_all = False  # флаг, чтобы избежать рекурсии toggle_all
        self._installing_in_progress = False
        # Счётчик «эпох» для check_installed_plugins. Если за время работы
        # фоновой проверки пользователь успел переключить версию AE — старый
        # ответ с устаревшими данными не должен перетереть новый.
        self._installed_check_epoch = 0

        # подключение сигналов потоков -> UI
        self.signals.log_added.connect(self._safe_log)
        self.signals.last_log_updated.connect(self._safe_update_last_log_line_ui)
        self.signals.installed_check_done.connect(self._apply_installed_marks)
        self.signals.progress_updated.connect(self._update_progress_ui)

        # --- сборка ---
        self._build_ui()

        # начальное наполнение списка плагинов
        for name, version, bat_path, _, size, _ in self.app.plugins_data:
            self.add_plugin_row(name, version, bat_path, size)

        # Учитываем «Old Red Giant mode»: скрываем Universe/Trapcode/MBS,
        # пока пользователь не включит галочку в Advanced.
        self.apply_old_rg_visibility()

        # отметка установленных
        self.check_installed_plugins()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        t = self._t()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(20)

        # === ЛЕВАЯ ПАНЕЛЬ ===
        left = QWidget(self)
        left.setFixedWidth(380)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Заголовок «Версия AE»
        self.lbl_version = QLabel(t.get("version_lbl", "Version"), left)
        self.lbl_version.setObjectName("TitleLabel")
        left_layout.addWidget(self.lbl_version)

        # SegmentedButton с версиями
        self.version_seg = SegmentedButton(self.AE_VERSIONS, left)
        self.version_seg.set_value(self.app.selected_ae_version or "None", emit=False)
        self.version_seg.valueChanged.connect(self._on_version_changed)
        
        # Обёртка для прижатия кнопок влево (не даем им растянуться на всю ширину панели)
        version_wrap = QHBoxLayout()
        version_wrap.setContentsMargins(0, 0, 0, 0)
        version_wrap.addWidget(self.version_seg)
        version_wrap.addStretch(1)
        left_layout.addLayout(version_wrap)

        # Разделитель между блоком версии AE и блоком списка плагинов
        left_layout.addSpacing(10)
        version_separator = QFrame(left)
        version_separator.setFrameShape(QFrame.Shape.HLine)
        version_separator.setFixedHeight(1)
        version_separator.setStyleSheet(
            f"background-color: {COLOR_BORDER}; border: none; max-height: 1px;"
        )
        left_layout.addWidget(version_separator)
        left_layout.addSpacing(10)

        # Заголовок «Плагины» + поиск
        plugins_header = QWidget(left)
        ph_layout = QHBoxLayout(plugins_header)
        ph_layout.setContentsMargins(0, 0, 0, 0)
        ph_layout.setSpacing(6)

        self.lbl_plugins = QLabel(t.get("plugins_lbl", "Plugins"), plugins_header)
        self.lbl_plugins.setObjectName("TitleLabel")
        ph_layout.addWidget(self.lbl_plugins)
        ph_layout.addStretch(1)

        self.lbl_search_icon = QLabel("⌕", plugins_header)  # ⌕ — монохромный glyph
        self.lbl_search_icon.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; "
            "font-family: 'Segoe UI Symbol', 'Arial'; "
            "font-size: 16px; font-weight: bold;"
        )
        self.lbl_search_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_layout.addWidget(self.lbl_search_icon)

        self.entry_search = QLineEdit(plugins_header)
        self.entry_search.setPlaceholderText(t.get("search_ph", "Search..."))
        self.entry_search.setFixedWidth(140)
        self.entry_search.setFixedHeight(28)
        self.entry_search.textChanged.connect(self.filter_plugins)
        ph_layout.addWidget(self.entry_search)

        left_layout.addWidget(plugins_header)

        # Скроллируемый список плагинов
        self.scroll = SmoothScrollArea(left)
        self.scroll.setObjectName("PluginsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Локальный QSS для выделения списка в карточку
        self.scroll.setStyleSheet(
            f"QScrollArea#PluginsScroll {{ background-color: {COLOR_CARD}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 10px; }}"
            f"QScrollArea#PluginsScroll > QWidget > QWidget {{ background-color: transparent; }}"
        )

        self.scroll_inner = QWidget()
        self.scroll_inner.setStyleSheet("background-color: transparent;")
        self.scroll_layout = QVBoxLayout(self.scroll_inner)
        self.scroll_layout.setContentsMargins(8, 8, 8, 8)
        self.scroll_layout.setSpacing(2)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # «Выбрать все» — стиль с тем же размером 22×22, что и у строк плагинов,
        # чтобы все чекбоксы в списке были визуально одинаковыми.
        self.cb_select_all = QCheckBox(t.get("select_all", "Select All"), self.scroll_inner)
        self.cb_select_all.setStyleSheet(
            f"QCheckBox {{ color: {COLOR_TEXT}; }}"
            "QCheckBox::indicator { width: 22px; height: 22px; "
            f"border-radius: 6px; border: 1px solid {COLOR_BORDER}; "
            "background-color: #1e1e1e; }"
            f"QCheckBox::indicator:hover {{ border: 1px solid {COLOR_ACCENT}; }}"
            f"QCheckBox::indicator:checked {{ background-color: {COLOR_ACCENT}; "
            f"border: 1px solid {COLOR_ACCENT}; "
            f'background-image: url("{CHECKMARK_DATA_URL}"); '
            "background-position: center; background-repeat: no-repeat; }"
        )
        self.cb_select_all.stateChanged.connect(self._on_select_all_toggled)
        self.scroll_layout.addWidget(self.cb_select_all)

        self.scroll.setWidget(self.scroll_inner)
        left_layout.addWidget(self.scroll, stretch=1)

        # Прогресс
        self.progress_label = QLabel(t.get("wait", "Waiting..."), left)
        self.progress_label.setObjectName("DimLabel")
        left_layout.addWidget(self.progress_label)

        self.progressbar = QProgressBar(left)
        self.progressbar.setRange(0, 1000)  # дробное прогрессирование (0.001)
        self.progressbar.setValue(0)
        self.progressbar.setTextVisible(False)
        self.progressbar.setFixedHeight(16)
        left_layout.addWidget(self.progressbar)

        # Кнопка «Установить»
        self.btn_install = QPushButton(t.get("install_btn", "Install Selected"), left)
        self.btn_install.setObjectName("InstallButton")
        self.btn_install.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_install.clicked.connect(self.start_installation)
        left_layout.addWidget(self.btn_install)

        # Чекбокс «Force Install»
        self.cb_force_install = QCheckBox(t.get("force_install", "Force Install"), left)
        self.cb_force_install.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 12px;")
        self.cb_force_install.stateChanged.connect(
            lambda state: setattr(self.app, "force_install", state == Qt.CheckState.Checked.value)
        )
        # центрируем
        force_wrap = QHBoxLayout()
        force_wrap.addStretch(1)
        force_wrap.addWidget(self.cb_force_install)
        force_wrap.addStretch(1)
        left_layout.addLayout(force_wrap)

        root.addWidget(left)

        # === ПРАВАЯ ПАНЕЛЬ (ЛОГ) ===
        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # Верх: лейбл + кнопка обновления + кнопка языка
        self.right_top = QWidget(right)
        rt_layout = QHBoxLayout(self.right_top)
        rt_layout.setContentsMargins(0, 0, 0, 0)
        rt_layout.setSpacing(6)

        self.lbl_log = QLabel(t.get("log_lbl", "Event Log"), self.right_top)
        self.lbl_log.setObjectName("TitleLabel")
        rt_layout.addWidget(self.lbl_log)
        rt_layout.addStretch(1)

        # Контейнер для будущей кнопки обновления (показывается из main_window)
        self.update_btn_container = QWidget(self.right_top)
        # [AKSIOM-FIX UI-22] Ограничиваем максимальную ширину, чтобы при
        # появлении update-кнопки не сжимать заголовок и кнопку языка.
        self.update_btn_container.setMaximumWidth(280)
        ubc_layout = QHBoxLayout(self.update_btn_container)
        ubc_layout.setContentsMargins(0, 0, 0, 0)
        ubc_layout.setSpacing(6)
        rt_layout.addWidget(self.update_btn_container)

        # [AKSIOM-FIX 2026-05] Маленькая кнопка очистки логов "⌫" удалена —
        # она дублировала кнопку "Очистить логи" в нижнем футере и только
        # засоряла верхнюю панель журнала.

        self.btn_lang = QPushButton(
            "EN" if self.app.current_lang == "ru" else "RU", self.right_top
        )
        self.btn_lang.setObjectName("LangButton")
        self.btn_lang.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lang.clicked.connect(self.app.toggle_language)
        rt_layout.addWidget(self.btn_lang)

        right_layout.addWidget(self.right_top)

        # Текстовое поле лога
        self.log_textbox = QTextEdit(right)
        self.log_textbox.setReadOnly(True)
        self.log_textbox.setPlaceholderText(
            t.get("log_empty", "Журнал событий пуст...\nЖдем ваших действий!")
        )
        right_layout.addWidget(self.log_textbox, stretch=1)

        root.addWidget(right, stretch=1)

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------
    def _t(self) -> dict[str, str]:
        return self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])

    # ------------------------------------------------------------------
    # Список плагинов: добавление строки и поиск
    # ------------------------------------------------------------------
    def add_plugin_row(self, name: str, version: str, bat_path: str, size: str) -> None:
        """Добавляет ряд с чекбоксом плагина (аналог _add_plugin_ui_row)."""
        is_custom = bat_path == "CUSTOM"
        accent = COLOR_CUSTOM if is_custom else COLOR_ACCENT
        accent_hov = COLOR_CUSTOM_HOV if is_custom else COLOR_ACCENT_HOV

        row = QWidget(self.scroll_inner)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(5, 2, 5, 2)
        row_layout.setSpacing(0)

        cb = QCheckBox(self.app.get_plugin_display_text(name, version, bat_path, size)
                       if hasattr(self.app, "get_plugin_display_text")
                       else self._fallback_display_text(name, version, bat_path, size),
                       row)
        # Базовый стиль (без явного цвета текста — ставим в _apply_installed_marks).
        # Сохраняем шаблон в атрибутах виджета, чтобы потом перерисовывать без
        # накопления правил.
        # [AKSIOM-FIX 2026-05] Унифицированный размер 22×22 для всех чекбоксов
        # в списке плагинов — раньше custom-плагины были 18×18, что выглядело
        # неаккуратно рядом с обычными плагинами и галочкой «Выбрать все».
        ind_size = 22
        ind_radius = 6
        # Важно: шаблон позже подставляется через str.format(color=...),
        # поэтому ВСЕ литеральные фигурные скобки CSS должны быть задвоены.
        cb._base_qss_template = (  # type: ignore[attr-defined]
            "QCheckBox {{ color: {color}; }}"
            f"QCheckBox::indicator {{{{ width: {ind_size}px; "
            f"height: {ind_size}px; "
            f"border-radius: {ind_radius}px; "
            f"border: 1px solid {COLOR_BORDER}; background-color: #1e1e1e; }}}}"
            f"QCheckBox::indicator:hover {{{{ border: 1px solid {accent}; }}}}"
            f"QCheckBox::indicator:checked {{{{ background-color: {accent}; "
            f"border: 1px solid {accent}; "
            f'background-image: url("{CHECKMARK_DATA_URL}"); '
            f"background-position: center; "
            f"background-repeat: no-repeat; }}}}"
        )
        cb.setStyleSheet(cb._base_qss_template.format(color=COLOR_TEXT))  # type: ignore[attr-defined]
        cb.stateChanged.connect(lambda _state, n=name, c=cb: self.on_plugin_toggle(n, c))

        row_layout.addWidget(cb)
        row_layout.addStretch(1)

        self.checkboxes.append((name, cb))
        self.checkbox_widgets[name] = cb
        self.plugin_rows[name] = row
        self.scroll_layout.addWidget(row)

    @staticmethod
    def _fallback_display_text(name: str, version: str, bat_path: str, size: str) -> str:
        """Делает версию и размер более тусклыми с помощью HTML."""
        prefix = "★ " if bat_path == "CUSTOM" else ""
        ver_text = "" if version == "1.0" else f" [v{version}]"
        return f"{prefix}<b>{name}</b> <span style='color:{COLOR_TEXT_DIM};'>{ver_text} ({size})</span>"

    def filter_plugins(self, *_args) -> None:
        """Скрывает строки, не подходящие под поисковый запрос."""
        query = self.entry_search.text().lower()
        self.app.search_text = query
        old_rg_off = not bool(getattr(self.app, "old_rg_mode", False))
        for name, cb in self.checkboxes:
            row = self.plugin_rows.get(name)
            if row is None:
                continue
            # Universe/Trapcode/MBS видны только когда включён старый RG-режим.
            if old_rg_off and name in ("Universe", "Trapcode", "MBS"):
                row.setVisible(False)
                continue
            visible = (query in name.lower()) or (query in cb.text().lower())
            row.setVisible(visible)

    def apply_old_rg_visibility(self) -> None:
        """
        Обновляет видимость Universe/Trapcode/MBS в списке плагинов в зависимости
        от флага self.app.old_rg_mode. Вызывается из advanced_frame после переключения
        галочки 'Old RedGiant mode'. Также сбрасывает чекбоксы скрытых плагинов,
        чтобы пользователь случайно не запустил установку невидимых плагинов.
        """
        old_rg_on = bool(getattr(self.app, "old_rg_mode", False))
        for name in ("Universe", "Trapcode", "MBS"):
            row = self.plugin_rows.get(name)
            cb = self.checkbox_widgets.get(name)
            if row is not None:
                if old_rg_on:
                    # Видимость на самом деле определит filter_plugins
                    # (учтёт текущий поисковый запрос).
                    row.setVisible(True)
                else:
                    row.setVisible(False)
            # Если плагины скрылись — снять с них галки, чтобы скрытый чекбокс
            # не уехал в selected_plugins при нажатии «Установить».
            if not old_rg_on and cb is not None and cb.isChecked():
                cb.setChecked(False)
        # Перепрогон фильтра — корректно учтёт поисковый запрос для видимых строк.
        self.filter_plugins()

    # ------------------------------------------------------------------
    # Чекбоксы: select all / индивидуальные
    # ------------------------------------------------------------------
    def _on_select_all_toggled(self, _state: int) -> None:
        if self._building_select_all:
            return
        state = self.cb_select_all.isChecked()
        self._building_select_all = True
        try:
            for _name, cb in self.checkboxes:
                cb.setChecked(state)
        finally:
            self._building_select_all = False
        if state:
            self._on_mass_select_warnings()

    def toggle_all(self) -> None:
        """Публичный аналог: включает/выключает все чекбоксы (по состоянию select_all)."""
        self._on_select_all_toggled(0)

    def on_plugin_toggle(self, plugin_name: str, cb: QCheckBox) -> None:
        """Вызывается при клике по конкретному чекбоксу плагина."""
        # синхронизация cb_select_all (без рекурсии)
        all_checked = all(c.isChecked() for _, c in self.checkboxes)
        self._building_select_all = True
        try:
            self.cb_select_all.setChecked(all_checked)
        finally:
            self._building_select_all = False

        if not cb.isChecked():
            return

        # warning для RSMB
        if plugin_name == "RSMB":
            ru = self.app.lang_dict.get("ru", {}).get(
                "rsmb_warn",
                "Мне не удалось сделать всю установку автоматически, поэтому вам "
                "придется нажать Extract самому (RSMB).",
            )
            en = self.app.lang_dict.get("en", {}).get(
                "rsmb_warn",
                "I could not automate the whole installation, so you will have to "
                "click Extract yourself (RSMB).",
            )
            self.log(f"⚠️ [ВНИМАНИЕ] {ru}", f"⚠️ [WARNING] {en}")

        # warning для пользовательских плагинов
        if plugin_name in self.app.custom_data:
            w_text = self.app.custom_data[plugin_name].get("warning_text", "").strip()
            w_popup = self.app.custom_data[plugin_name].get("warning_popup", False)
            if w_text:
                self.log(
                    f"⚠️ [ВНИМАНИЕ - {plugin_name}] {w_text}",
                    f"⚠️ [WARNING - {plugin_name}] {w_text}",
                )
                if w_popup:
                    t = self._t()
                    QMessageBox.warning(self, t.get("warn_title", "Warning"), w_text)

    def _on_mass_select_warnings(self) -> None:
        """Аналог блока в toggle_all из оригинала: собирает попапы предупреждений."""
        ru = self.app.lang_dict.get("ru", {}).get("rsmb_warn", "")
        en = self.app.lang_dict.get("en", {}).get("rsmb_warn", "")
        if ru or en:
            self.log(f"⚠️ [ВНИМАНИЕ] {ru}", f"⚠️ [WARNING] {en}")

        popups: list[str] = []
        for name, _cb in self.checkboxes:
            if name in self.app.custom_data:
                w_text = self.app.custom_data[name].get("warning_text", "").strip()
                w_popup = self.app.custom_data[name].get("warning_popup", False)
                if w_text:
                    self.log(
                        f"⚠️ [ВНИМАНИЕ - {name}] {w_text}",
                        f"⚠️ [WARNING - {name}] {w_text}",
                    )
                    if w_popup:
                        popups.append(f"{name}:\n{w_text}")
        if popups:
            t = self._t()
            QMessageBox.warning(self, t.get("warn_title", "Warning"), "\n\n".join(popups))

    # ------------------------------------------------------------------
    # Версия AE
    # ------------------------------------------------------------------
    def _on_version_changed(self, value: str) -> None:
        self.app.selected_ae_version = value
        self.check_installed_plugins()

    # ------------------------------------------------------------------
    # Проверка установленных плагинов
    # ------------------------------------------------------------------
    def check_installed_plugins(self) -> None:
        """Запускает фоновую проверку установленных плагинов для текущей версии AE."""
        ae_ver = self.app.selected_ae_version or "None"
        full_ver = "20" + ae_ver if ae_ver != "None" else "None"
        self._installed_check_epoch += 1
        epoch = self._installed_check_epoch
        threading.Thread(
            target=self._async_check_installed,
            args=(full_ver, epoch),
            daemon=True,
        ).start()

    def _async_check_installed(self, full_ver: str, epoch: int) -> None:
        """В фоне определяет, установлен ли каждый плагин."""
        is_installed = getattr(self.app, "is_plugin_installed", None)
        results: dict[str, bool] = {}
        for name, _cb in self.checkboxes:
            # Если за время работы успели запустить новую проверку —
            # перестаём тратить время на эту, ответ всё равно отбросится.
            if epoch != self._installed_check_epoch:
                return
            if full_ver == "None" or is_installed is None:
                results[name] = False
            else:
                try:
                    results[name] = bool(is_installed(name, full_ver))
                except Exception as exc:  # noqa: BLE001
                    print(f"is_plugin_installed({name}): {exc}")
                    results[name] = False
        # Поздний ответ — игнорируем
        if epoch != self._installed_check_epoch:
            return
        self.signals.installed_check_done.emit(results)

    def _apply_installed_marks(self, results: dict) -> None:
        """Окрашивает названия установленных плагинов в зелёный."""
        for name, installed in results.items():
            cb = self.checkbox_widgets.get(name)
            if cb is None:
                continue
            # Используем сохранённый шаблон, чтобы не накапливать QSS-правила
            template = getattr(cb, "_base_qss_template", None)
            color = "#4CAF50" if installed else COLOR_TEXT
            if template:
                cb.setStyleSheet(template.format(color=color))
            else:
                # fallback (на случай если строка добавлена в обход add_plugin_row)
                cb.setStyleSheet(f"QCheckBox {{ color: {color}; }}")

    # ------------------------------------------------------------------
    # Логи
    # ------------------------------------------------------------------
    def log(self, ru_text: str, en_text: str | None = None) -> None:
        """Потокобезопасное логирование (отправляет сигнал в UI-поток)."""
        if en_text is None:
            en_text = ru_text
        self.signals.log_added.emit(ru_text, en_text)

    def _safe_log(self, ru_text: str, en_text: str) -> None:
        """Слот сигнала log_added — выполняется в главном потоке."""
        entry = {"ru": ru_text, "en": en_text}
        self.app.log_history.append(entry)
        self.app.persistent_log_history.append(entry)

        msg = ru_text if self.app.current_lang == "ru" else en_text
        self.log_textbox.append(msg)

        # дублируем в advanced (если уже создан)
        adv = getattr(self.app, "advanced_frame_widget", None)
        if adv is not None and hasattr(adv, "append_log"):
            adv.append_log(msg + "\n")

    def _update_last_log_line(self, ru_text: str, en_text: str | None = None) -> None:
        """Перезапись последней строки лога (для прогресса загрузки).

        [AKSIOM-FIX UI-3] persistent_log_history НЕ трогаем — там может
        накапливаться огромная история, и `[-1]` после переполнения
        deque(maxlen) может указывать вообще на чужую запись. История
        прогресса не критична для архива; достаточно обновить log_history
        и UI.
        """
        if en_text is None:
            en_text = ru_text
        entry = {"ru": ru_text, "en": en_text}
        if self.app.log_history:
            self.app.log_history[-1] = entry
        self.signals.last_log_updated.emit(ru_text, en_text)

    def _safe_update_last_log_line_ui(self, ru_text: str, en_text: str) -> None:
        """Слот сигнала last_log_updated.

        [AKSIOM-FIX UI-1] Используем StartOfBlock+KeepAnchor, чтобы выделить
        ровно последнюю «логическую» строку (QTextBlock), а не visual line —
        иначе после log_added (который добавляет новый блок) курсор стоит
        на пустой следующей строке и LineUnderCursor выделит её, оставив
        предыдущую запись на месте → дублирование прогресса.

        [AKSIOM-FIX UI-9] Скролл вниз только если пользователь и так стоит
        в самом низу. Иначе при просмотре старого лога во время загрузки
        каждое обновление прогресса дёргает скролл вниз.
        """
        msg = ru_text if self.app.current_lang == "ru" else en_text

        bar = self.log_textbox.verticalScrollBar()
        auto_follow = bar.value() >= bar.maximum() - 4

        cursor = self.log_textbox.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        # Если последний блок пустой (хвостовой newline после append) —
        # отступаем в предыдущий, чтобы переписывать именно текстовую
        # последнюю строку.
        if cursor.atBlockStart() and cursor.blockNumber() > 0:
            cursor.movePosition(cursor.MoveOperation.PreviousBlock)
            cursor.movePosition(cursor.MoveOperation.EndOfBlock)
        cursor.movePosition(
            cursor.MoveOperation.StartOfBlock,
            cursor.MoveMode.KeepAnchor,
        )
        cursor.removeSelectedText()
        cursor.insertText(msg)
        self.log_textbox.setTextCursor(cursor)
        if auto_follow:
            self.log_textbox.ensureCursorVisible()

        adv = getattr(self.app, "advanced_frame_widget", None)
        if adv is not None and hasattr(adv, "update_last_log"):
            adv.update_last_log(msg)

    def clear_logs(self) -> None:
        # [AKSIOM-FIX UI-4] Чистим всю историю; иначе _update_last_log_line
        # может попытаться обновить устаревшую запись в persistent.
        self.app.log_history.clear()
        if hasattr(self.app, "persistent_log_history"):
            try:
                self.app.persistent_log_history.clear()
            except AttributeError:
                pass
        self.log_textbox.clear()

    # ------------------------------------------------------------------
    # Прогрессбар
    # ------------------------------------------------------------------
    def _update_progress_ui(self, text: str, value: float) -> None:
        self.progress_label.setText(text)
        self.progressbar.setValue(int(value * 1000))

    # ------------------------------------------------------------------
    # Установка — делегируем главному классу
    # ------------------------------------------------------------------
    def start_installation(self) -> None:
        """Кнопка «Установить»: вся логика в AksiomInstaller.start_installation."""
        self.app.start_installation()

    # ------------------------------------------------------------------
    # Обновление текстов при смене языка (вызывается из main_window.toggle_language)
    # ------------------------------------------------------------------
    def retranslate(self) -> None:
        t = self._t()
        self.lbl_version.setText(t.get("version_lbl", "Version"))
        self.lbl_plugins.setText(t.get("plugins_lbl", "Plugins"))
        self.entry_search.setPlaceholderText(t.get("search_ph", "Search..."))
        self.cb_select_all.setText(t.get("select_all", "Select All"))
        self.cb_force_install.setText(t.get("force_install", "Force Install"))
        self.btn_install.setText(t.get("install_btn", "Install Selected"))
        self.lbl_log.setText(t.get("log_lbl", "Event Log"))
        self.btn_lang.setText("EN" if self.app.current_lang == "ru" else "RU")

        if self.progressbar.value() in (0, 1000):
            self.progress_label.setText(
                t.get("complete", "Complete")
                if self.progressbar.value() == 1000
                else t.get("wait", "Waiting...")
            )

        # перерисовать тексты чекбоксов через get_plugin_display_text
        if hasattr(self.app, "update_all_plugin_labels"):
            self.app.update_all_plugin_labels()

        # перезалить лог в нужной локали
        self.log_textbox.clear()
        for entry in self.app.log_history:
            self.log_textbox.append(entry.get(self.app.current_lang, entry["en"]))