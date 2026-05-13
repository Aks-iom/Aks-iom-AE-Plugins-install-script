# -*- coding: utf-8 -*-
"""
styles.py
Глобальная палитра, QSS-стили тёмной темы и кастомный SegmentedButton (аналог CTkSegmentedButton).
"""

import base64
import os
import tempfile
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QButtonGroup, QSizePolicy

# ---------------------------------------------------------------------------
# Цветовая палитра, адаптированная под скриншот
# ---------------------------------------------------------------------------
COLOR_BG          = "#1c1c22"   # Тёмный фон окна (как на референсе)
COLOR_CARD        = "#252530"   # Фон карточки списка плагинов / сайдбара
COLOR_CARD_ALT    = "#2a2a35"   # Фон полей ввода / поиска
COLOR_LOG_BG      = "#15151a"   # Очень тёмный фон лога
COLOR_BORDER      = "#34343c"   # Тонкие рамки
COLOR_BORDER_HOV  = "#3e3e48"   # Ховер на тёмных кнопках
COLOR_ACCENT      = "#7560d6"   # Фирменный фиолетовый
COLOR_ACCENT_HOV  = "#624fbb"   # Hover акцентного цвета
COLOR_TEXT        = "#e0e0e0"   # Основной белый текст
COLOR_TEXT_DIM    = "#8a8a92"   # Вторичный текст
COLOR_TEXT_MUTED  = "#666666"   # Ссылки в футере
COLOR_SCROLL      = "#4a4a55"   # Ползунок скроллбара (приглушённый)
COLOR_SCROLL_HOV  = "#6c6c78"   # Ползунок при наведении

# Возвращены для совместимости с install_tab.py
COLOR_CUSTOM      = "#9b59b6"   # Пользовательские плагины
COLOR_CUSTOM_HOV  = "#8e44ad"   # Hover пользовательских плагинов
COLOR_TITLE       = "#7560d6"   # Заголовок сплэша

FONT_FAMILY       = "Segoe UI"  # Шрифт


# ---------------------------------------------------------------------------
# Иконка-галочка для чекбоксов.
# Qt 6 ненадёжно загружает image: url(data:image/...;base64,...) в QSS,
# поэтому мы при импорте модуля разворачиваем PNG-галочку в файл во
# временной папке системы и используем file:///-URL — это работает всегда.
# ---------------------------------------------------------------------------
_CHECKMARK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAABe0lEQVR42s2V"
    "MS8FQRSFZ5+H34H4MUoh6BSeoNL6JVqJSq9U6ZVa4Qdo5b2595w5ip151gbZ"
    "fVbiVpPNne+cOXcyG8IfVzU0UNJSCEEhBFVVpSHBVZdvC8MljUIIwemXpN9I"
    "jyt/Ab9SLgq3klYHhzvNnOb12u8/DScPqD9cNRx0Q3I5DVnstTSPGhtHv4Eb"
    "I3JETzPNNsu1ChAOXL6VAeMucKrEUpzP4S/SdH2+CbLzMhwI+xm03AXedg7i"
    "RZpuzI0a7CI3OgRQTEDcqxselvvCpx/wpbJRFJIhJqclCCSRXL5bXHSJ5Ut4"
    "zn6SlASBTkvGWIuIdM12mnH1ct4sCId1/o4iwloE7rPtfM+vF4IXd1A8+iSC"
    "mJKSnPYG4S7fa3SKpV0PeZgRcZJdwmnJaSmJkiRjZC/nP5zkuC1SnC8Mb4sY"
    "7KQpMgj8C5HTImKINgi8PRPIzubPL/GsIeCNk4yzyAnFO2m6Nhj8u5e1y0vb"
    "+6ffhFZVlcJ/q3d5sDVDHxopCAAAAABJRU5ErkJggg=="
)

def _ensure_check_png() -> str:
    """
    Записывает галочку-PNG во временную папку и возвращает путь, пригодный
    для использования в QSS image:/background-image: url(...).
    Перезапись делается каждый раз — это нужно, чтобы при обновлении
    приложения новая версия PNG-галочки заменяла старую.
    """
    target = os.path.join(tempfile.gettempdir(), "aksiom_check.png")
    try:
        with open(target, "wb") as f:
            f.write(base64.b64decode(_CHECKMARK_PNG_B64))
    except OSError:
        pass
    # Qt принимает прямые пути с прямыми слэшами в QSS. Используем именно их.
    return target.replace("\\", "/")

CHECKMARK_PATH = _ensure_check_png()
CHECKMARK_DATA_URL = CHECKMARK_PATH  # имя сохранено для обратной совместимости


# ---------------------------------------------------------------------------
# Глобальный QSS-stylesheet
# ---------------------------------------------------------------------------
GLOBAL_STYLESHEET = f"""
/* ---------- Базовое окно ---------- */
QMainWindow, QDialog, QWidget {{
    background-color: {COLOR_BG};
    color: {COLOR_TEXT};
    font-family: "{FONT_FAMILY}";
    font-size: 13px;
}}

/* ---------- Тулты ---------- */
QToolTip {{
    background-color: {COLOR_CARD};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    padding: 4px;
}}

/* ---------- Метки ---------- */
QLabel {{
    background-color: transparent;
    color: {COLOR_TEXT};
}}
QLabel#TitleLabel {{
    font-size: 15px;
    font-weight: bold;
}}
QLabel#SplashTitle {{
    color: {COLOR_ACCENT};
    font-size: 20px;
    font-weight: bold;
}}
QLabel#SplashStatus {{
    color: {COLOR_TEXT_DIM};
    font-size: 13px;
}}
QLabel#DimLabel {{
    color: {COLOR_TEXT_DIM};
}}

/* ---------- Кнопки ---------- */
QPushButton {{
    background-color: {COLOR_ACCENT};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: bold;
    outline: none; /* Убираем системную рамку фокуса */
}}
QPushButton:hover {{
    background-color: {COLOR_ACCENT_HOV};
}}
QPushButton:disabled {{
    background-color: #3a3a3e;
    color: #777777;
}}

/* Тёмная вторичная кнопка (Очистить логи и т.п.) */
QPushButton#DarkButton {{
    background-color: {COLOR_BORDER};
    color: {COLOR_TEXT};
    font-weight: normal;
}}
QPushButton#DarkButton:hover {{
    background-color: {COLOR_BORDER_HOV};
}}

/* Кнопка-ссылка (футер) */
QPushButton#LinkButton {{
    background-color: transparent;
    color: {COLOR_TEXT_MUTED};
    text-decoration: underline;
    font-weight: normal;
    font-size: 13px;
    padding: 2px 4px;
}}
QPushButton#LinkButton:hover {{
    color: {COLOR_TEXT};
}}

/* Кнопка боковой панели */
QPushButton#SidebarButton {{
    background-color: transparent;
    color: {COLOR_TEXT};
    text-align: left;
    font-weight: normal;
    padding: 8px 12px;
    border-left: 3px solid transparent;
    border-radius: 6px;
}}
QPushButton#SidebarButton:hover {{
    background-color: {COLOR_BORDER};
}}
QPushButton#SidebarButton:checked {{
    background-color: #2f2a44;
    color: {COLOR_ACCENT};
    border-left: 3px solid {COLOR_ACCENT};
    font-weight: bold;
}}

/* Кнопка переключения языка */
QPushButton#LangButton {{
    background-color: {COLOR_BORDER};
    color: {COLOR_TEXT};
    font-size: 12px;
    font-weight: bold;
    padding: 4px;
    border-radius: 4px;
    min-width: 32px;
    max-width: 32px;
    min-height: 24px;
    max-height: 24px;
}}
QPushButton#LangButton:hover {{
    background-color: {COLOR_BORDER_HOV};
}}

/* Кнопка установки (большая, акцентная) */
QPushButton#InstallButton {{
    font-size: 15px;
    font-weight: bold;
    padding: 10px 16px;
    min-height: 38px;
    border-radius: 8px;
}}

/* ---------- Поля ввода ---------- */
QLineEdit {{
    background-color: {COLOR_CARD_ALT};
    color: {COLOR_TEXT};
    border: 1px solid transparent;
    border-radius: 14px;
    padding: 4px 12px;
    selection-background-color: {COLOR_ACCENT};
}}
QLineEdit:focus {{
    border: 1px solid {COLOR_ACCENT};
}}

QTextEdit, QPlainTextEdit {{
    background-color: {COLOR_LOG_BG};
    color: {COLOR_TEXT_DIM};
    border: 1px solid {COLOR_BORDER};
    border-radius: 10px;
    font-family: "Consolas", monospace;
    font-size: 12px;
    padding: 12px;
}}

/* ---------- Чекбоксы ---------- */
QCheckBox {{
    color: {COLOR_TEXT};
    spacing: 10px;
    background-color: transparent;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 1.5px solid #55555a;
    border-radius: 4px;
    background-color: transparent;
}}
QCheckBox::indicator:hover {{
    border: 1.5px solid {COLOR_ACCENT};
}}
QCheckBox::indicator:checked {{
    background-color: {COLOR_ACCENT};
    border: 1.5px solid {COLOR_ACCENT};
    background-image: url("{CHECKMARK_DATA_URL}");
    background-position: center;
    background-repeat: no-repeat;
}}

/* ---------- Прогресс-бар ---------- */
QProgressBar {{
    background-color: {COLOR_BORDER};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {COLOR_ACCENT};
    border-radius: 3px;
}}

/* ---------- Скроллбары (Интегрированные) ---------- */
QScrollBar:vertical {{
    background-color: {COLOR_CARD_ALT};
    width: 14px;
    margin: 2px;
    border-radius: 6px;
}}
QScrollBar::handle:vertical {{
    background-color: {COLOR_SCROLL};
    border-radius: 5px;
    min-height: 36px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {COLOR_SCROLL_HOV};
}}
QScrollBar::handle:vertical:pressed {{
    background-color: {COLOR_ACCENT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
    border: none;
    width: 0;
    height: 0;
}}

QScrollBar:horizontal {{
    background-color: {COLOR_CARD_ALT};
    height: 14px;
    margin: 2px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal {{
    background-color: {COLOR_SCROLL};
    border-radius: 5px;
    min-width: 36px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {COLOR_SCROLL_HOV};
}}
QScrollBar::handle:horizontal:pressed {{
    background-color: {COLOR_ACCENT};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
    border: none;
    width: 0;
    height: 0;
}}

/* ---------- Скролл-области ---------- */
QScrollArea, QScrollArea > QWidget > QWidget {{
    background-color: transparent;
    border: none;
}}

/* ---------- Карточки/боковая панель ---------- */
QWidget#Card {{
    background-color: {COLOR_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 12px;
}}
QWidget#Sidebar {{
    background-color: {COLOR_CARD};
    border-right: 1px solid {COLOR_BORDER};
}}

/* ---------- SegmentedButton ---------- */
QWidget#SegmentedContainer {{
    background-color: {COLOR_BORDER}; 
    border: none;
    border-radius: 6px;
}}
QPushButton#SegmentButton {{
    background-color: {COLOR_BG};
    color: {COLOR_TEXT_DIM};
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    min-width: 36px; /* Фиксированная минимальная ширина чтобы ничего не сжималось */
    font-weight: bold;
    outline: none;
}}
QPushButton#SegmentButton:hover {{
    background-color: {COLOR_CARD_ALT};
    color: {COLOR_TEXT};
}}
QPushButton#SegmentButton:checked {{
    background-color: {COLOR_ACCENT};
    color: white;
}}
"""


# ---------------------------------------------------------------------------
# SegmentedButton — кастомный аналог CTkSegmentedButton
# ---------------------------------------------------------------------------
class SegmentedButton(QWidget):
    """
    Группа взаимоисключающих кнопок.
    """

    valueChanged = pyqtSignal(str)

    def __init__(self, values=None, parent=None):
        super().__init__(parent)
        self.setObjectName("SegmentedContainer")
        
        # ВАЖНО: Разрешаем QWidget рисовать фон (background-color) из QSS!
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        
        # Позволяем контейнеру сжаться до реального размера кнопок, чтобы не растягивался
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3) # Толщина внешней рамки
        self._layout.setSpacing(3) # Отступ между кнопками внутри

        self._current_value: str | None = None

        if values:
            self.set_values(values)

    # ----- public API ------------------------------------------------------
    def set_values(self, values: list[str]) -> None:
        """Полностью заменяет список вариантов."""
        # Очистка старых кнопок
        for btn in self._buttons.values():
            self._group.removeButton(btn)
            self._layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()

        # [AKSIOM-FIX UI-11] Защита от пустого values — иначе _current_value
        # остаётся старым и любой последующий set_value('что-то') упадёт KeyError.
        if not values:
            self._current_value = None
            return

        # Создание новых кнопок
        for value in values:
            btn = QPushButton(value, self)
            btn.setObjectName("SegmentButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
            # Дополнительная защита от системной рамки фокуса
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            
            # Если текст длинный (например, "None"), даем ему больше места
            # чтобы пружина (addStretch) его не сплющила.
            if len(value) > 4:
                btn.setMinimumWidth(80)

            btn.clicked.connect(lambda _checked, v=value: self._on_clicked(v))

            self._buttons[value] = btn
            self._group.addButton(btn)
            self._layout.addWidget(btn)

        if self._current_value not in values:
            self.set_value(values[0], emit=False)
        else:
            self._buttons[self._current_value].setChecked(True)

    def set_value(self, value: str, emit: bool = True) -> None:
        """Программно установить выбранное значение."""
        if value not in self._buttons:
            return
        self._current_value = value
        self._buttons[value].setChecked(True)
        if emit:
            self.valueChanged.emit(value)

    def value(self) -> str | None:
        return self._current_value

    def update_label(self, old_value: str, new_value: str) -> None:
        """Переименовать кнопку (для смены языка), сохранив текущий выбор."""
        if old_value not in self._buttons:
            return
        btn = self._buttons.pop(old_value)
        btn.setText(new_value)
        try:
            btn.clicked.disconnect()
        except TypeError:
            pass
        btn.clicked.connect(lambda _checked, v=new_value: self._on_clicked(v))
        self._buttons[new_value] = btn
        if self._current_value == old_value:
            self._current_value = new_value

    # ----- internal --------------------------------------------------------
    def _on_clicked(self, value: str) -> None:
        if value == self._current_value:
            return
        self._current_value = value
        self.valueChanged.emit(value)


# ---------------------------------------------------------------------------
# Алиас для обратной совместимости с main.py
# ---------------------------------------------------------------------------
GLOBAL_QSS = GLOBAL_STYLESHEET