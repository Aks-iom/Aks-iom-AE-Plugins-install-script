# -*- coding: utf-8 -*-
"""
advanced_frame.py
Вкладка «Дополнительно» — сайдбар + QStackedWidget с 7 экранами:
  Changelog, Logs, Custom Plugins, Individual Paths, Export/Import, Uninstall, Misc.
"""

from __future__ import annotations

import json
import os
import shutil
import random
import sys
import traceback
from typing import TYPE_CHECKING

# Windows-нативное проигрывание WAV — самый надёжный бэкенд.
# Стандартная либа, не требует установки. На не-Windows будет недоступна.
try:
    import winsound  # type: ignore
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

from PyQt6.QtCore import Qt, QTimer, QObject, QEvent, QPropertyAnimation, QEasingCurve, QPoint, pyqtProperty, QUrl
from PyQt6.QtGui import QPixmap

# QSoundEffect — Qt-нативный бэкенд для коротких WAV. Используется как fallback,
# если winsound недоступен или не отрабатывает (например, на Linux/Mac).
try:
    from PyQt6.QtMultimedia import QSoundEffect
    HAS_QSOUNDEFFECT = True
except ImportError:
    HAS_QSOUNDEFFECT = False
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Прячем приветственное сообщение pygame из консоли
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
try:
    import pygame
    pygame.mixer.init()
    HAS_PYGAME = True
except Exception:
    HAS_PYGAME = False

from styles import (
    CHECKMARK_DATA_URL,
    COLOR_ACCENT, COLOR_ACCENT_HOV, COLOR_BORDER, COLOR_CARD,
    COLOR_TEXT, COLOR_TEXT_DIM, SegmentedButton,
)

if TYPE_CHECKING:
    from main_window import AksiomInstaller

_DESTRUCTIVE_BTN_QSS = (
    "QPushButton { background-color: #552222; color: white; "
    "border-radius: 6px; padding: 6px 12px; font-weight: bold; outline: none; }"
    "QPushButton:hover { background-color: #772222; }"
)
_DELETE_X_BTN_QSS = (
    "QPushButton { background-color: #882222; color: white; "
    "border-radius: 4px; font-weight: bold; padding: 0; outline: none; }"
    "QPushButton:hover { background-color: #aa3333; }"
)
_DARK_BTN_QSS = (
    "QPushButton { background-color: #333333; color: #cccccc; "
    "border-radius: 6px; padding: 6px 12px; outline: none; }"
    "QPushButton:hover { background-color: #444444; }"
)

# ---------------------------------------------------------------------------
# Утилита для путей
# ---------------------------------------------------------------------------
def get_resource_path(relative_path):
    """ Получает абсолютный путь к файлу, работает и в IDE, и в PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ---------------------------------------------------------------------------
# Проигрыватель звука для мамбо-режима с поддержкой НАЛОЖЕНИЯ.
#
# Каждый клик = новый одновременный звук. Если кликов 5 в секунду —
# 5 экземпляров mambo.wav играют параллельно, накладываясь друг на друга.
#
# Порядок попыток (в _select_backend) теперь оптимизирован для overlap:
#   1. pygame.mixer (8 каналов из коробки) — лучший overlap.
#                   Sound.play() возвращает Channel, на котором играет;
#                   pygame сам выбирает свободный канал. Если все заняты —
#                   звук просто не играет (поведение при спаме — нормально).
#   2. QSoundEffect — пул из POOL_SIZE экземпляров, по кругу round-robin.
#                     Каждый клик берёт следующий по индексу — даже если
#                     текущий ещё играет, у нас N-1 «свежих» в запасе.
#   3. winsound — НЕ умеет overlap нативно (PlaySound держит одну очередь).
#                 Запускаем каждый звук в отдельном потоке через PlaySound,
#                 НО даже это не даст overlap — winsound разделяет один
#                 буфер. Оставлено только как «лучше один срез, чем тишина».
#                 Если установлен pygame или QtMultimedia — winsound
#                 принципиально не выбирается.
#
# Если ни один бэкенд недоступен — звук просто не играет.
# ---------------------------------------------------------------------------
class MamboSoundPlayer:
    """Проигрыватель короткого WAV с поддержкой наложения звуков."""

    POOL_SIZE = 8  # сколько одновременных воспроизведений поддерживать

    def __init__(self, wav_path: str, log_fn=None) -> None:
        self.wav_path = wav_path
        self.log_fn = log_fn or (lambda _msg: None)
        self.backend: str = "none"
        # winsound
        self._winsound_flags: int = 0
        # qsound — пул эффектов и round-robin индекс
        self._qsound_pool: list = []
        self._qsound_idx: int = 0
        # pygame
        self._pygame_sound = None
        self._select_backend()

    # ------------------------------------------------------------------
    def _log(self, msg: str) -> None:
        try:
            print(f"[MamboSound] {msg}")
        except Exception:
            pass
        try:
            self.log_fn(msg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _select_backend(self) -> None:
        if not self.wav_path or not os.path.exists(self.wav_path):
            self._log(f"WAV не найден: {self.wav_path}")
            return

        # 1. pygame — overlap из коробки через каналы микшера
        if HAS_PYGAME:
            try:
                # Увеличиваем количество каналов микшера, чтобы наложение
                # выдерживало много кликов подряд. По умолчанию у pygame
                # обычно 8, ставим явно POOL_SIZE на случай старых версий.
                try:
                    pygame.mixer.set_num_channels(self.POOL_SIZE)
                except Exception:
                    pass
                self._pygame_sound = pygame.mixer.Sound(self.wav_path)
                self.backend = "pygame"
                self._log(
                    f"backend=pygame, file={self.wav_path}, "
                    f"channels={self.POOL_SIZE} (overlap supported)"
                )
                return
            except Exception as exc:  # noqa: BLE001
                self._log(f"pygame init failed: {exc}")

        # 2. QSoundEffect — пул экземпляров, round-robin
        if HAS_QSOUNDEFFECT:
            try:
                url = QUrl.fromLocalFile(self.wav_path)
                pool = []
                for _ in range(self.POOL_SIZE):
                    eff = QSoundEffect()
                    eff.setSource(url)
                    eff.setVolume(1.0)
                    pool.append(eff)
                self._qsound_pool = pool
                self._qsound_idx = 0
                self.backend = "qsound"
                self._log(
                    f"backend=qsound, file={self.wav_path}, "
                    f"pool_size={self.POOL_SIZE} (overlap supported)"
                )
                return
            except Exception as exc:  # noqa: BLE001
                self._log(f"QSoundEffect init failed: {exc}")

        # 3. winsound — последний фолбэк (overlap НЕ работает!)
        if HAS_WINSOUND:
            try:
                self._winsound_flags = (
                    winsound.SND_ASYNC
                    | winsound.SND_NODEFAULT
                    | winsound.SND_FILENAME
                )
                self.backend = "winsound"
                self._log(
                    f"backend=winsound, file={self.wav_path} "
                    f"(NO overlap — каждый новый клик прервёт текущий)"
                )
                return
            except Exception as exc:  # noqa: BLE001
                self._log(f"winsound init failed: {exc}")

        self._log("Ни один бэкенд недоступен — звук не будет играть.")

    # ------------------------------------------------------------------
    def play(self) -> None:
        """Запускает новый экземпляр звука. На pygame и qsound он накладывается
        на уже играющие; на winsound — прерывает предыдущий."""
        if self.backend == "pygame" and self._pygame_sound is not None:
            try:
                # pygame.mixer.Sound.play() сам выбирает свободный Channel
                # из микшера. Если все POOL_SIZE заняты — звук пропускается
                # (это нормальная защита от очередей).
                self._pygame_sound.play()
            except Exception as exc:  # noqa: BLE001
                self._log(f"pygame play failed: {exc}")

        elif self.backend == "qsound" and self._qsound_pool:
            try:
                # Round-robin: берём следующий эффект из пула. К моменту,
                # когда мы вернёмся к нему через POOL_SIZE кликов, он почти
                # наверняка уже доиграл (mambo.wav короткий).
                eff = self._qsound_pool[self._qsound_idx]
                self._qsound_idx = (self._qsound_idx + 1) % len(self._qsound_pool)
                # Если этот конкретный эффект ВСЁ ЕЩЁ играет (очень частые
                # клики) — stop+play, иначе play() будет проигнорирован Qt'ом.
                # Другие N-1 эффектов продолжат играть параллельно — overlap.
                if eff.isPlaying():
                    eff.stop()
                eff.play()
            except Exception as exc:  # noqa: BLE001
                self._log(f"qsound play failed: {exc}")

        elif self.backend == "winsound":
            try:
                winsound.PlaySound(self.wav_path, self._winsound_flags)
            except Exception as exc:  # noqa: BLE001
                self._log(f"winsound play failed: {exc}")

    # ------------------------------------------------------------------
    def stop(self) -> None:
        """Останавливает все звуки (вызывается при выходе из режима)."""
        if self.backend == "pygame" and self._pygame_sound is not None:
            try:
                self._pygame_sound.stop()
            except Exception:
                pass
        elif self.backend == "qsound":
            for eff in self._qsound_pool:
                try:
                    eff.stop()
                except Exception:
                    pass
        elif self.backend == "winsound":
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Перехватчик кликов в режиме МАМБО.
# По каждому клику:
#   1) проигрывает звук mambo (через MamboSoundPlayer с тройным fallback),
#   2) дёргает callback, который показывает анимированную pop-картинку.
# Установка/снятие фильтра — через _on_mambo_changed.
# ---------------------------------------------------------------------------
class MamboClickFilter(QObject):
    """Sound-плеер кэшируется в __init__ и переиспользуется на каждый клик.
    Раньше каждое нажатие создавало новый pygame.mixer.Sound = чтение и
    парсинг WAV-файла с диска.

    Hariki easter-egg:
      С вероятностью HARIKI_CHANCE на каждый клик играется альтернативный
      звук hariki.wav и показывается hariki.jpg вместо случайной mambo-картинки.
      Звук Hariki проигрывается ДВАЖДЫ подряд через pool — каналы микшера
      накладываются, что даёт ~+6 dB субъективной громкости (digital gain
      в WAV уже на максимуме после loudness normalization).
    """

    HARIKI_CHANCE = 0.01  # 1% шанс на клик. 0.0 — отключить, 1.0 — каждый клик.

    def __init__(self, parent=None, pop_callback=None, log_fn=None,
                 hariki_pop_callback=None):
        super().__init__(parent)
        self._pop_callback = pop_callback
        self._hariki_pop_callback = hariki_pop_callback

        # Основной звук
        wav_path = get_resource_path("mambo_assets/mambo.wav")
        self._player = MamboSoundPlayer(wav_path, log_fn=log_fn)

        # Hariki — отдельный плеер (отдельный пул каналов/эффектов).
        # Если файла нет — _player.backend == "none" и play() будет no-op.
        hariki_wav = get_resource_path("mambo_assets/hariki.wav")
        self._hariki_player = MamboSoundPlayer(hariki_wav, log_fn=log_fn)

    def set_pop_callback(self, cb) -> None:
        self._pop_callback = cb

    def set_hariki_pop_callback(self, cb) -> None:
        self._hariki_pop_callback = cb

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            # Бросаем кубик: hariki или mambo?
            is_hariki = (
                self._hariki_player.backend != "none"
                and random.random() < self.HARIKI_CHANCE
            )

            if is_hariki:
                # Hariki — играем ДВАЖДЫ подряд. На pygame/qsound это значит
                # два одновременных воспроизведения = ~+6 dB субъективно.
                # На winsound второй вызов прервёт первый — overlap не будет,
                # просто останется один проигрыватель (это норм fallback).
                self._hariki_player.play()
                self._hariki_player.play()
                if self._hariki_pop_callback is not None:
                    try:
                        self._hariki_pop_callback()
                    except Exception:
                        pass
            else:
                # Обычный mambo
                self._player.play()
                if self._pop_callback is not None:
                    try:
                        self._pop_callback()
                    except Exception:
                        pass
        return False


# ---------------------------------------------------------------------------
# Всплывающая картинка-оверлей для МАМБО-режима.
# Каждый pop:
#   1) выбирает случайно одну из mambo_pop_*.jpg
#   2) появляется снизу окна с плавным fade-in + slide-up
#   3) висит в центре ~600 мс
#   4) уплывает вверх с fade-out
# Если pop запросили во время текущей анимации — она прерывается и
# заменяется новой (актуальная картинка всегда «свежая»).
# ---------------------------------------------------------------------------
class MamboPopOverlay(QLabel):
    """Полупрозрачный QLabel поверх главного окна, показывающий случайную
    pop-картинку с трёхфазной анимацией: snap-up → hold → fly-out."""

    APPEAR_MS = 350      # появление снизу
    HOLD_MS = 600        # задержка по центру
    DISAPPEAR_MS = 350   # уход вверх
    SLIDE_DISTANCE = 80  # px смещения при появлении/уходе
    MAX_HEIGHT = 320     # px — масштабируем картинку под высоту

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        # Не перехватываем клики (чтобы не блокировать сам режим)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()

        # Эффект прозрачности — для fade анимаций
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        # Ссылки на анимации/таймер, чтобы прерывать в любой момент.
        self._anim_pos: QPropertyAnimation | None = None
        self._anim_op: QPropertyAnimation | None = None
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._start_disappear)

        # Кэш загруженных pixmap (избегаем перечитывания JPG при каждом клике)
        self._pix_cache: dict[str, QPixmap] = {}
        self._candidate_paths: list[str] = []
        self._refresh_candidate_paths()

    def _refresh_candidate_paths(self) -> None:
        """Ищем mambo_pop_*.jpg/png/webp в mambo_assets."""
        assets_dir = get_resource_path("mambo_assets")
        result: list[str] = []
        if os.path.isdir(assets_dir):
            for name in os.listdir(assets_dir):
                low = name.lower()
                if low.startswith("mambo_pop") and low.endswith(
                    (".jpg", ".jpeg", ".png", ".webp")
                ):
                    result.append(os.path.join(assets_dir, name))
        self._candidate_paths = result

    def _load_pixmap(self, path: str) -> QPixmap | None:
        cached = self._pix_cache.get(path)
        if cached is not None:
            return cached
        pix = QPixmap(path)
        if pix.isNull():
            return None
        # масштабируем по высоте, сохраняя пропорции — большие картинки
        # не должны лезть за пределы окна
        if pix.height() > self.MAX_HEIGHT:
            pix = pix.scaledToHeight(
                self.MAX_HEIGHT,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._pix_cache[path] = pix
        return pix

    def trigger(self) -> None:
        """Запускает один цикл анимации со случайной mambo_pop_*-картинкой."""
        if not self._candidate_paths:
            self._refresh_candidate_paths()
            if not self._candidate_paths:
                return
        path = random.choice(self._candidate_paths)
        self._trigger_with_path(path)

    def trigger_path(self, path: str) -> None:
        """Запускает анимацию КОНКРЕТНОЙ картинки (для Hariki easter-egg)."""
        if not path or not os.path.exists(path):
            return
        self._trigger_with_path(path)

    def _trigger_with_path(self, path: str) -> None:
        pix = self._load_pixmap(path)
        if pix is None:
            return

        # Прерываем текущую анимацию, если есть
        self._stop_animations()

        self.setPixmap(pix)
        self.resize(pix.size())

        parent = self.parentWidget()
        if parent is None:
            return

        # Целевая позиция — горизонтальный центр, вертикально по центру
        target_x = (parent.width() - self.width()) // 2
        target_y = (parent.height() - self.height()) // 2
        start_y = target_y + self.SLIDE_DISTANCE  # появляемся снизу

        self.move(target_x, start_y)
        self._opacity.setOpacity(0.0)
        self.show()
        self.raise_()

        # 1) Появление: slide вверх + fade-in
        self._anim_pos = QPropertyAnimation(self, b"pos", self)
        self._anim_pos.setDuration(self.APPEAR_MS)
        self._anim_pos.setStartValue(QPoint(target_x, start_y))
        self._anim_pos.setEndValue(QPoint(target_x, target_y))
        self._anim_pos.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._anim_op = QPropertyAnimation(self._opacity, b"opacity", self)
        self._anim_op.setDuration(self.APPEAR_MS)
        self._anim_op.setStartValue(0.0)
        self._anim_op.setEndValue(1.0)
        self._anim_op.setEasingCurve(QEasingCurve.Type.OutCubic)

        # По окончании появления — взводим таймер на HOLD_MS
        self._anim_pos.finished.connect(self._on_appear_done)

        self._anim_pos.start()
        self._anim_op.start()

    def _on_appear_done(self) -> None:
        if not self.isVisible():
            return
        self._hold_timer.start(self.HOLD_MS)

    def _start_disappear(self) -> None:
        if not self.isVisible():
            return
        parent = self.parentWidget()
        if parent is None:
            self.hide()
            return

        cur_pos = self.pos()
        end_pos = QPoint(cur_pos.x(), cur_pos.y() - self.SLIDE_DISTANCE)

        self._stop_animations(stop_hold=False)

        self._anim_pos = QPropertyAnimation(self, b"pos", self)
        self._anim_pos.setDuration(self.DISAPPEAR_MS)
        self._anim_pos.setStartValue(cur_pos)
        self._anim_pos.setEndValue(end_pos)
        self._anim_pos.setEasingCurve(QEasingCurve.Type.InCubic)

        self._anim_op = QPropertyAnimation(self._opacity, b"opacity", self)
        self._anim_op.setDuration(self.DISAPPEAR_MS)
        self._anim_op.setStartValue(self._opacity.opacity())
        self._anim_op.setEndValue(0.0)
        self._anim_op.setEasingCurve(QEasingCurve.Type.InCubic)

        self._anim_op.finished.connect(self._finalize_hide)
        self._anim_pos.start()
        self._anim_op.start()

    def _finalize_hide(self) -> None:
        # Не прячем, если за это время уже стартовала новая appear-анимация
        if self._anim_op is not None and self._anim_op.endValue() == 0.0:
            self.hide()

    def _stop_animations(self, stop_hold: bool = True) -> None:
        if self._anim_pos is not None:
            try:
                self._anim_pos.stop()
            except Exception:
                pass
            self._anim_pos = None
        if self._anim_op is not None:
            try:
                self._anim_op.stop()
            except Exception:
                pass
            self._anim_op = None
        if stop_hold and self._hold_timer.isActive():
            self._hold_timer.stop()

    def cancel(self) -> None:
        """Принудительно скрыть оверлей (вызывается при выходе из режима)."""
        self._stop_animations()
        self._opacity.setOpacity(0.0)
        self.hide()


# ---------------------------------------------------------------------------
# Основной класс
# ---------------------------------------------------------------------------
class AdvancedFrame(QWidget):
    PAGES = ("changelog", "logs", "custom", "settings", "sync", "uninstall", "options")

    def __init__(self, app: "AksiomInstaller", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.path_entries: dict[str, QLineEdit] = {}
        self.current_editing_plugin: str | None = None
        self.selected_types: list[str] = ["zip"]
        self.type_buttons: dict[str, QPushButton] = {}
        self.type_source: dict[str, str] = {}
        self.type_gdrive: dict[str, str] = {}
        self.type_local: dict[str, str] = {}
        self.type_path: dict[str, str] = {}
        self.type_ext: dict[str, str] = {}
        self.dynamic_path_wrapper = None
        self.custom_list_inner = None
        self.custom_form_inner = None
        self.un_version: str = self.app.selected_ae_version or "None"

        # МАМБО
        # Слайд-таймер с фоновой картинкой больше НЕ используется —
        # вместо него pop-картинка появляется по клику (см. MamboPopOverlay).
        self.is_mambo_active = False
        # Lazy: создаётся при первом включении режима, parent = главное окно
        # (чтобы pop-картинка показывалась поверх ВСЕГО, а не только этой вкладки).
        self.mambo_pop: MamboPopOverlay | None = None
        self.mambo_filter = MamboClickFilter(
            self,
            pop_callback=self._mambo_trigger_pop,
            log_fn=self._mambo_log,
            hariki_pop_callback=self._mambo_trigger_hariki_pop,
        )

        self._build_ui()
        self.show_page("changelog")

    def _mambo_trigger_pop(self) -> None:
        """Вызывается из MamboClickFilter на обычном клике в режиме МАМБО.
        Показывает случайную mambo_pop_*-картинку."""
        if not self.is_mambo_active:
            return
        if self.mambo_pop is None:
            return
        host = self.mambo_pop.parentWidget()
        if host is None or not host.isVisible():
            return
        self.mambo_pop.trigger()

    def _mambo_trigger_hariki_pop(self) -> None:
        """Вызывается на «секретном» Hariki-клике (HARIKI_CHANCE).
        Показывает hariki-картинку. Если файл не найден — НИЧЕГО не показывает
        (раньше был fallback на случайную mambo-картинку, что давало баг
        «звук Hariki, а картинка mambo»)."""
        if not self.is_mambo_active:
            return
        if self.mambo_pop is None:
            return
        host = self.mambo_pop.parentWidget()
        if host is None or not host.isVisible():
            return

        # Ищем файл в нескольких регистрах/расширениях. На Linux ФС регистро-
        # зависима, на Windows — нет, но для портативности обрабатываем все
        # варианты явно. Кэшируем найденный путь, чтобы не сканировать диск
        # на каждый клик.
        path = self._resolve_hariki_image()
        if path is None:
            # файла действительно нет — НЕ показываем mambo-картинку,
            # просто звук без визуала. В лог пишем один раз, чтобы было
            # видно при диагностике.
            if not getattr(self, "_hariki_missing_warned", False):
                self._mambo_log(
                    "hariki.jpg не найден в mambo_assets/ — pop-картинка "
                    "не будет показываться. Положи файл в папку и пересобери."
                )
                self._hariki_missing_warned = True
            return
        self.mambo_pop.trigger_path(path)

    def _resolve_hariki_image(self) -> str | None:
        """Кэшируемый поиск hariki-картинки. Возвращает абсолютный путь
        или None, если ни один из вариантов имени не найден."""
        # Кэш — чтобы не делать os.path.exists на каждый клик
        cached = getattr(self, "_hariki_image_cache", "__unset__")
        if cached != "__unset__":
            return cached  # либо путь, либо None — оба валидные значения

        candidates = [
            "mambo_assets/hariki.jpg",
            "mambo_assets/hariki.jpeg",
            "mambo_assets/hariki.png",
            "mambo_assets/hariki.webp",
            "mambo_assets/Hariki.jpg",   # на случай, если положили с большой буквы
            "mambo_assets/Hariki.JPG",
            "mambo_assets/Hariki.jpeg",
            "mambo_assets/Hariki.png",
        ]
        found: str | None = None
        for rel in candidates:
            full = get_resource_path(rel)
            if os.path.exists(full):
                found = full
                self._mambo_log(f"hariki image: {rel}")
                break

        self._hariki_image_cache = found
        return found

    def _mambo_log(self, msg: str) -> None:
        """[AKSIOM-FIX 2026-05] Логирование mambo-режима полностью отключено
        по запросу пользователя — диагностические сообщения «[Mambo] ...»
        больше не попадают в журнал событий и не засоряют его. Метод
        оставлен как no-op, чтобы существующие call-sites не падали.
        Если когда-нибудь снова понадобится диагностика, можно временно
        раскомментировать строку ниже.
        """
        # log = getattr(self.app, "log", None)
        # if log is not None:
        #     try:
        #         log(f"[Mambo] {msg}", f"[Mambo] {msg}")
        #     except Exception:
        #         pass
        return

    def _t(self) -> dict[str, str]:
        return self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QWidget(self)
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(180)
        sb_layout = QVBoxLayout(self.sidebar)
        sb_layout.setContentsMargins(10, 20, 10, 20)
        sb_layout.setSpacing(5)

        self.sidebar_btns: dict[str, QPushButton] = {}
        self.sidebar_group = QButtonGroup(self)
        self.sidebar_group.setExclusive(True)

        t = self._t()
        labels = {
            "changelog": t.get("tab_changelog", "Changelog"),
            "logs": t.get("tab_logs", "Logs"),
            "custom": t.get("tab_custom", "Custom Plugins"),
            "settings": t.get("tab_settings", "Individual Paths"),
            "sync": t.get("tab_sync", "Export / Import"),
            "uninstall": t.get("tab_uninstall", "Uninstall"),
            "options": t.get("tab_options", "Misc"),
        }
        for page_id in self.PAGES:
            btn = QPushButton(labels[page_id], self.sidebar)
            btn.setObjectName("SidebarButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked, pid=page_id: self.show_page(pid))
            sb_layout.addWidget(btn)
            self.sidebar_btns[page_id] = btn
            self.sidebar_group.addButton(btn)
        sb_layout.addStretch(1)

        root.addWidget(self.sidebar)
        self.stack = QStackedWidget(self)
        root.addWidget(self.stack, stretch=1)

        self.page_changelog = self._build_changelog_page()
        self.page_logs = self._build_logs_page()
        self.page_custom = self._build_custom_page()
        self.page_settings = self._build_settings_page()
        self.page_sync = self._build_sync_page()
        self.page_uninstall = self._build_uninstall_page()
        self.page_options = self._build_options_page()

        for page in (self.page_changelog, self.page_logs, self.page_custom, 
                     self.page_settings, self.page_sync, self.page_uninstall, self.page_options):
            self.stack.addWidget(page)

        self._page_index = {
            "changelog": 0, "logs": 1, "custom": 2,
            "settings": 3, "sync": 4, "uninstall": 5, "options": 6,
        }

    def show_page(self, page_id: str) -> None:
        idx = self._page_index.get(page_id)
        if idx is None: return
        self.stack.setCurrentIndex(idx)
        btn = self.sidebar_btns.get(page_id)
        if btn: btn.setChecked(True)

        if page_id == "settings": self.build_settings_ui()
        elif page_id == "sync": self.build_sync_ui()
        elif page_id == "uninstall":
            self.un_version = self.app.selected_ae_version or "None"
            if hasattr(self, "un_seg"): self.un_seg.set_value(self.un_version, emit=False)
            self.build_uninstall_ui()
        elif page_id == "custom": self.build_custom_ui()
        elif page_id == "options": self.update_drive_widget()
        elif page_id == "logs": self.populate_logs()

    # --- CHANGELOG ---
    def _build_changelog_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        self.changelog_text = QTextEdit(page)
        self.changelog_text.setReadOnly(True)
        self.changelog_text.setPlainText(self.app.CHANGELOG_TEXT.get(self.app.current_lang, ""))
        layout.addWidget(self.changelog_text)
        return page

    # --- LOGS ---
    def _build_logs_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        self.adv_log_textbox = QTextEdit(page)
        self.adv_log_textbox.setReadOnly(True)
        layout.addWidget(self.adv_log_textbox, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_export_logs = QPushButton(self._t().get("export_log_btn", "Export Logs"), page)
        self.btn_export_logs.setObjectName("DarkButton")
        self.btn_export_logs.clicked.connect(self.export_persistent_logs)
        btn_row.addWidget(self.btn_export_logs)
        layout.addLayout(btn_row)
        return page

    def populate_logs(self) -> None:
        """[AKSIOM-FIX UI-25] Один setPlainText вместо тысяч append() —
        иначе при больших persistent_log_history (после fix #6 — до 10k записей)
        открытие вкладки замораживает UI на секунды."""
        if not hasattr(self, "adv_log_textbox"): return
        lang = self.app.current_lang
        lines = [
            entry.get(lang, entry.get("en", ""))
            for entry in self.app.persistent_log_history
        ]
        self.adv_log_textbox.setPlainText("\n".join(lines))
        # автоскролл вниз
        sb = self.adv_log_textbox.verticalScrollBar()
        sb.setValue(sb.maximum())

    def append_log(self, text: str) -> None:
        if hasattr(self, "adv_log_textbox"):
            self.adv_log_textbox.moveCursor(self.adv_log_textbox.textCursor().MoveOperation.End)
            self.adv_log_textbox.insertPlainText(text)
            self.adv_log_textbox.ensureCursorVisible()

    def update_last_log(self, text: str) -> None:
        if not hasattr(self, "adv_log_textbox"): return
        cursor = self.adv_log_textbox.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.select(cursor.SelectionType.LineUnderCursor)
        cursor.removeSelectedText()
        cursor.insertText(text)
        self.adv_log_textbox.setTextCursor(cursor)
        self.adv_log_textbox.ensureCursorVisible()

    def export_persistent_logs(self) -> None:
        if not self.app.persistent_log_history: return
        path, _ = QFileDialog.getSaveFileName(self, "Save logs", "logs.txt", "Text files (*.txt)")
        if not path: return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"--- AE Plugins Installer Persistent Logs ({self.app.CURRENT_VERSION}) ---\n\n")
                for entry in self.app.persistent_log_history:
                    f.write(entry.get(self.app.current_lang, entry["en"]) + "\n")
        except OSError as exc: print(f"Error exporting logs: {exc}")

    # --- CUSTOM PLUGINS ---
    def _build_custom_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        left = QWidget(page)
        left.setObjectName("Sidebar")
        left.setFixedWidth(250)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(15, 20, 15, 20)
        left_layout.setSpacing(10)

        self.btn_new_custom = QPushButton(
            self._t().get("c_new_btn", "+ New Plugin"), left
        )
        self.btn_new_custom.clicked.connect(lambda: self.load_plugin_to_form(None))
        left_layout.addWidget(self.btn_new_custom)

        self.custom_list_scroll = QScrollArea(left)
        self.custom_list_scroll.setWidgetResizable(True)
        self.custom_list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.custom_list_inner = QWidget()
        self.custom_list_layout = QVBoxLayout(self.custom_list_inner)
        self.custom_list_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_list_layout.setSpacing(2)
        self.custom_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.custom_list_scroll.setWidget(self.custom_list_inner)
        left_layout.addWidget(self.custom_list_scroll, stretch=1)
        layout.addWidget(left)

        self.custom_form_scroll = QScrollArea(page)
        self.custom_form_scroll.setWidgetResizable(True)
        self.custom_form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.custom_form_inner = QWidget()
        self.custom_form_layout = QVBoxLayout(self.custom_form_inner)
        self.custom_form_layout.setContentsMargins(30, 30, 30, 30)
        self.custom_form_layout.setSpacing(8)
        self.custom_form_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.custom_form_scroll.setWidget(self.custom_form_inner)
        layout.addWidget(self.custom_form_scroll, stretch=1)
        return page

    def build_custom_ui(self, plugin_to_load: str | None = None) -> None:
        while self.custom_list_layout.count():
            item = self.custom_list_layout.takeAt(0)
            if item.widget() is not None: item.widget().deleteLater()

        for name in sorted(self.app.custom_data.keys(), key=str.casefold):
            btn = QPushButton(name, self.custom_list_inner)
            btn.setObjectName("SidebarButton")
            btn.clicked.connect(lambda _checked, n=name: self.load_plugin_to_form(n))
            self.custom_list_layout.addWidget(btn)
        self.load_plugin_to_form(plugin_to_load)

    def load_plugin_to_form(self, plugin_name: str | None = None) -> None:
        self.current_editing_plugin = plugin_name
        data = self.app.custom_data.get(plugin_name, {}) if plugin_name else {}
        t = self._t()

        while self.custom_form_layout.count():
            item = self.custom_form_layout.takeAt(0)
            if item.widget() is not None: item.widget().deleteLater()

        custom_files = data.get("custom_files", {})
        for t_id in ("zip", "exe", "file", "reg"):
            cf = custom_files.get(t_id, {})
            self.type_source[t_id] = "Google Drive" if cf.get("source") == "gdrive" else t.get("local_file", "Локальный файл")
            self.type_gdrive[t_id] = f"https://drive.google.com/file/d/{cf.get('gdrive_id')}/view" if cf.get("gdrive_id") else ""
            self.type_local[t_id] = cf.get("filename", "")
            self.type_path[t_id] = cf.get("target_path", "")
            if t_id == "file" and cf.get("source") == "gdrive":
                ext = os.path.splitext(cf.get("filename", ""))[1]
                self.type_ext[t_id] = "" if ext == ".file" else ext
            else:
                self.type_ext[t_id] = ""

        self.selected_types = list(data.get("c_types", ["zip"]))
        self.custom_form_layout.setSpacing(16)

        if plugin_name:
            edit_prefix = t.get("c_edit_title", "Editing:")
            lbl_title = QLabel(f"{edit_prefix} {plugin_name}", self.custom_form_inner)
        else:
            lbl_title = QLabel(t.get("c_new_title", "New Plugin"), self.custom_form_inner)
        lbl_title.setObjectName("TitleLabel")
        self.custom_form_layout.addWidget(lbl_title)

        lbl_name = self._dim_label(t.get("c_name_ph", "Название") + " *")
        self.custom_form_layout.addWidget(lbl_name)
        self.c_name_edit = QLineEdit(data.get("name", ""), self.custom_form_inner)
        self.custom_form_layout.addWidget(self.c_name_edit)

        row = QHBoxLayout()
        col_v = QVBoxLayout()
        col_v.addWidget(self._dim_label(t.get("c_ver_ph", "Версия")))
        self.c_ver_edit = QLineEdit(data.get("version", ""), self.custom_form_inner)
        col_v.addWidget(self.c_ver_edit)
        row.addLayout(col_v, stretch=1)

        col_s = QVBoxLayout()
        col_s.addWidget(self._dim_label(t.get("c_size_ph", "Размер")))
        self.c_size_edit = QLineEdit(data.get("size", ""), self.custom_form_inner)
        col_s.addWidget(self.c_size_edit)
        row.addLayout(col_s, stretch=1)
        self.custom_form_layout.addLayout(row)

        self.custom_form_layout.addWidget(self._dim_label(t.get("c_warn_ph", "Текст предупреждения")))
        warn_row = QHBoxLayout()
        self.c_warn_edit = QLineEdit(data.get("warning_text", ""), self.custom_form_inner)
        warn_row.addWidget(self.c_warn_edit, stretch=1)
        self.c_warn_popup_cb = QCheckBox(t.get("c_warn_popup", "Показать в окне"), self.custom_form_inner)
        self.c_warn_popup_cb.setChecked(bool(data.get("warning_popup", False)))
        warn_row.addWidget(self.c_warn_popup_cb)
        self.custom_form_layout.addLayout(warn_row)

        lbl_type = QLabel(t.get("plugin_type", "Выбор типа файлов"), self.custom_form_inner)
        lbl_type.setStyleSheet("font-weight: bold;")
        self.custom_form_layout.addWidget(lbl_type)

        type_box = QWidget(self.custom_form_inner)
        type_box.setObjectName("SegmentedContainer")
        type_layout = QHBoxLayout(type_box)
        type_layout.setContentsMargins(4, 4, 4, 4)
        type_layout.setSpacing(4)

        self.type_buttons = {}
        for t_name, t_id in [("ZIP", "zip"), ("EXE", "exe"), ("FILE", "file"), ("REG", "reg")]:
            btn = QPushButton(t_name, type_box)
            btn.setCheckable(True)
            btn.setChecked(t_id in self.selected_types)
            btn.setObjectName("SegmentButton")
            btn.clicked.connect(lambda _c, tid=t_id: self._toggle_custom_type(tid))
            type_layout.addWidget(btn, stretch=1)
            self.type_buttons[t_id] = btn
        self.custom_form_layout.addWidget(type_box)

        self.dynamic_path_wrapper = QWidget(self.custom_form_inner)
        self.dynamic_path_layout = QVBoxLayout(self.dynamic_path_wrapper)
        self.dynamic_path_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_form_layout.addWidget(self.dynamic_path_wrapper)
        self._render_type_fields()

        btn_row = QHBoxLayout()
        btn_save = QPushButton(t.get("save_btn", "Сохранить"), self.custom_form_inner)
        btn_save.setObjectName("InstallButton")
        btn_save.setMinimumWidth(180)
        btn_save.clicked.connect(self.save_managed_custom_plugin)
        btn_row.addWidget(btn_save)

        if plugin_name:
            btn_dup = QPushButton(t.get("c_duplicate_btn", "Duplicate"), self.custom_form_inner)
            btn_dup.setObjectName("DarkButton")
            btn_dup.clicked.connect(self.duplicate_current_custom_plugin)
            btn_row.addWidget(btn_dup)

            btn_del = QPushButton(t.get("c_delete_btn", "Delete"), self.custom_form_inner)
            btn_del.setStyleSheet(_DESTRUCTIVE_BTN_QSS)
            btn_del.clicked.connect(lambda: self.delete_custom_plugin(plugin_name))
            btn_row.addWidget(btn_del)
        btn_row.addStretch(1)
        self.custom_form_layout.addLayout(btn_row)

    def _render_type_fields(self) -> None:
        if self.dynamic_path_wrapper is None: return
        while self.dynamic_path_layout.count():
            item = self.dynamic_path_layout.takeAt(0)
            if item.widget() is not None: item.widget().deleteLater()
        t = self._t()
        local_text = t.get("local_file", "Локальный файл")
        for t_id in self.selected_types:
            card = QWidget(self.dynamic_path_wrapper)
            card.setObjectName("Card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 10, 10, 10)
            card_layout.setSpacing(8)

            lbl = QLabel(f"{t.get('setup_for', 'Настройка для')} .{t_id.upper()}", card)
            lbl.setStyleSheet(f"color: {COLOR_ACCENT}; font-weight: bold;")
            card_layout.addWidget(lbl)

            current_mode = self.type_source.get(t_id, local_text)
            seg = SegmentedButton(["Google Drive", local_text], card)
            seg.set_value(current_mode, emit=False)
            seg.valueChanged.connect(lambda val, tid=t_id: self._on_source_changed(tid, val))
            # [AKSIOM-FIX 2026-05] Центрируем переключатель источника
            # внутри карточки — SegmentedButton имеет sizePolicy Maximum,
            # поэтому без обёртки прижимается к левому краю.
            seg_row = QHBoxLayout()
            seg_row.setContentsMargins(0, 0, 0, 0)
            seg_row.addStretch(1)
            seg_row.addWidget(seg)
            seg_row.addStretch(1)
            card_layout.addLayout(seg_row)

            input_row = QHBoxLayout()
            if current_mode == "Google Drive":
                input_row.addWidget(self._dim_label(t.get("link_lbl", "Ссылка:")))
                gdrive_edit = QLineEdit(self.type_gdrive.get(t_id, ""), card)
                gdrive_edit.textChanged.connect(lambda txt, tid=t_id: self.type_gdrive.__setitem__(tid, txt))
                input_row.addWidget(gdrive_edit, stretch=1)
                if t_id == "file":
                    input_row.addWidget(self._dim_label(t.get("format_lbl", "Format:")))
                    ext_edit = QLineEdit(self.type_ext.get(t_id, ""), card)
                    ext_edit.setFixedWidth(70)
                    ext_edit.textChanged.connect(lambda txt, tid=t_id: self.type_ext.__setitem__(tid, txt))
                    input_row.addWidget(ext_edit)
            else:
                input_row.addWidget(self._dim_label(t.get("file_lbl", "Файл:")))
                local_edit = QLineEdit(self.type_local.get(t_id, ""), card)
                local_edit.textChanged.connect(lambda txt, tid=t_id: self.type_local.__setitem__(tid, txt))
                input_row.addWidget(local_edit, stretch=1)
                btn_browse = QPushButton(t.get("browse", "Обзор"), card)
                btn_browse.clicked.connect(lambda _c, tid=t_id, e=local_edit: self._browse_local_file(tid, e))
                input_row.addWidget(btn_browse)
            card_layout.addLayout(input_row)

            if t_id in ("zip", "file"):
                path_row = QHBoxLayout()
                path_row.addWidget(self._dim_label(t.get("folder_lbl", "Папка:")))
                path_edit = QLineEdit(self.type_path.get(t_id, ""), card)
                path_edit.textChanged.connect(lambda txt, tid=t_id: self.type_path.__setitem__(tid, txt))
                path_row.addWidget(path_edit, stretch=1)
                btn_path = QPushButton(t.get("browse", "Обзор"), card)
                btn_path.clicked.connect(lambda _c, tid=t_id, e=path_edit: self._browse_target_path(tid, e))
                path_row.addWidget(btn_path)
                card_layout.addLayout(path_row)
            self.dynamic_path_layout.addWidget(card)

    def _on_source_changed(self, t_id: str, val: str) -> None:
        self.type_source[t_id] = val
        QTimer.singleShot(50, self._render_type_fields)

    def _toggle_custom_type(self, t_id: str) -> None:
        if t_id in self.selected_types: self.selected_types.remove(t_id)
        else: self.selected_types.append(t_id)
        for tid, btn in self.type_buttons.items(): btn.setChecked(tid in self.selected_types)
        self._render_type_fields()

    def _browse_local_file(self, t_id: str, edit: QLineEdit) -> None:
        t = self._t()
        path, _ = QFileDialog.getOpenFileName(
            self, t.get("select_file", "Select file")
        )
        if path:
            self.type_local[t_id] = path
            edit.setText(path)

    def _browse_target_path(self, t_id: str, edit: QLineEdit) -> None:
        t = self._t()
        path = QFileDialog.getExistingDirectory(
            self, t.get("target_folder", "Select folder")
        )
        if path:
            self.type_path[t_id] = path
            edit.setText(path)

    def save_managed_custom_plugin(self) -> None:
        t = self._t()
        if self.c_name_edit is None: return
        try:
            name = self.c_name_edit.text().strip().replace(" ", "_")
            if not name or not self.selected_types:
                QMessageBox.warning(self, t.get("warn_title", "Warning"), t.get("warn_fields", "'Name' and file types are required!"))
                return
            old_name = self.current_editing_plugin
            if name != old_name and any(p[0].lower() == name.lower() for p in self.app.plugins_data):
                QMessageBox.critical(self, t.get("err_title", "Error"), t.get("err_exists", "Plugin with this name already exists!"))
                return

            custom_files: dict[str, dict] = {}
            for t_id in self.selected_types:
                mode = "gdrive" if self.type_source.get(t_id) == "Google Drive" else "local"
                file_info: dict[str, str] = {"source": mode}
                if mode == "gdrive":
                    if t_id == "file":
                        ext = (self.type_ext.get(t_id) or "").strip()
                        if ext and not ext.startswith("."): ext = "." + ext
                        if not ext: ext = ".file" 
                        c_filename = f"{name}_{t_id}{ext}"
                    else:
                        c_filename = f"{name}_{t_id}.{t_id}"
                    file_info["filename"] = c_filename
                    raw_link = (self.type_gdrive.get(t_id) or "").strip()
                    gdrive_id = self.app.extract_gdrive_id(raw_link)
                    if not gdrive_id:
                        QMessageBox.critical(
                            self,
                            t.get("err_title", "Error"),
                            t.get("err_invalid_gdrive", "Invalid Google Drive link for .{ext}").format(ext=t_id),
                        )
                        return
                    file_info["gdrive_id"] = gdrive_id
                else:
                    local_src = (self.type_local.get(t_id) or "").strip()
                    ext = os.path.splitext(local_src)[1] if local_src else f".{t_id}"
                    c_filename = f"{name}_{t_id}{ext}"
                    file_info["filename"] = c_filename
                    if os.path.isabs(local_src):
                        if not os.path.exists(local_src):
                            QMessageBox.critical(
                                self,
                                t.get("err_title", "Error"),
                                t.get("err_local_not_found", "Local file not found for .{ext}").format(ext=t_id),
                            )
                            return
                        dest_path = os.path.join(self.app.base_dir, c_filename)
                        try: shutil.copy2(local_src, dest_path)
                        except OSError as exc:
                            QMessageBox.critical(
                                self,
                                t.get("err_title", "Error"),
                                t.get("err_copy", "Copy error: {err}").format(err=exc),
                            )
                            return
                    elif not local_src:
                        QMessageBox.critical(
                            self,
                            t.get("err_title", "Error"),
                            t.get("err_specify_local", "Specify a local file for .{ext}").format(ext=t_id),
                        )
                        return
                target = (self.type_path.get(t_id) or "").strip()
                if target: file_info["target_path"] = target
                custom_files[t_id] = file_info

            new_plugin = {
                "name": name, "version": self.c_ver_edit.text().strip() or "1.0",
                "size": self.c_size_edit.text().strip() or "? MB", "bat_path": "CUSTOM",
                "c_types": list(self.selected_types), "custom_files": custom_files,
                "warning_text": self.c_warn_edit.text().strip(),
                "warning_popup": self.c_warn_popup_cb.isChecked(),
            }
            target_db_path = os.path.join(self.app.custom_configs_dir, "custom_plugins.json")
            data: dict = {"plugins": []}
            if old_name:
                for filename in os.listdir(self.app.custom_configs_dir):
                    if not filename.endswith(".json"): continue
                    filepath = os.path.join(self.app.custom_configs_dir, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f: test_data = json.load(f)
                        if any(p.get("name") == old_name for p in test_data.get("plugins", [])):
                            target_db_path = filepath
                            data = test_data
                            break
                    except Exception: pass
            if not old_name or not data.get("plugins"):
                if os.path.exists(target_db_path):
                    try:
                        with open(target_db_path, "r", encoding="utf-8") as f: loaded = json.load(f)
                        if isinstance(loaded, dict) and "plugins" in loaded: data = loaded
                    except Exception: pass
            if old_name:
                data["plugins"] = [p for p in data.get("plugins", []) if p.get("name") != old_name]
            data["plugins"].append(new_plugin)
            try:
                with open(target_db_path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
            except OSError as exc:
                QMessageBox.critical(
                    self,
                    t.get("err_title", "Error"),
                    t.get("err_save_json", "Failed to save JSON: {err}").format(err=exc),
                )
                return
            self.app.reload_custom_plugins()
            QTimer.singleShot(50, lambda n=name: self.build_custom_ui(n))
            if self.stack.currentIndex() == self._page_index["sync"]:
                QTimer.singleShot(50, self.build_sync_ui)
        except Exception as exc:
            QMessageBox.critical(
                self,
                t.get("err_critical_title", "Critical error"),
                t.get("err_critical_save", "An error occurred while saving:\n{err}").format(err=exc),
            )

    def duplicate_current_custom_plugin(self) -> None:
        if not self.current_editing_plugin or self.c_name_edit is None: return
        self.c_name_edit.setText(self.c_name_edit.text() + "_copy")
        self.current_editing_plugin = None
        QMessageBox.information(
            self,
            self._t().get("info_title", "Info"),
            self._t().get(
                "plugin_copied_msg",
                "Plugin copied. Edit the fields and press “Save”.",
            ),
        )

    def delete_custom_plugin(self, name: str) -> None:
        t = self._t()
        reply = QMessageBox.question(self, t.get("un_confirm_title", "Confirm"), f"{t.get('un_confirm_msg', 'Delete')} {name}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        for filename in os.listdir(self.app.custom_configs_dir):
            if not filename.endswith(".json"): continue
            filepath = os.path.join(self.app.custom_configs_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f: data = json.load(f)
                original = data.get("plugins", [])
                data["plugins"] = [p for p in original if p.get("name") != name]
                if len(data["plugins"]) < len(original):
                    with open(filepath, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
                    break
            except Exception as exc: print(f"Error deleting {name}: {exc}")
        if hasattr(self.app, "reload_custom_plugins"): self.app.reload_custom_plugins()
        QTimer.singleShot(50, self.build_custom_ui)

    # --- INDIVIDUAL PATHS ---
    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 30, 20, 20)
        layout.setSpacing(15)
        header = QHBoxLayout()
        self.lbl_settings_title = QLabel(self._t().get("settings_title", "Individual Paths"), page)
        self.lbl_settings_title.setObjectName("TitleLabel")
        header.addWidget(self.lbl_settings_title)
        header.addStretch(1)
        self.btn_reset_all = QPushButton(self._t().get("reset_all", "Reset All"), page)
        self.btn_reset_all.setStyleSheet(_DESTRUCTIVE_BTN_QSS)
        self.btn_reset_all.clicked.connect(self.reset_all_paths)
        header.addWidget(self.btn_reset_all)
        layout.addLayout(header)

        self.settings_scroll = QScrollArea(page)
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_inner = QWidget()
        self.settings_layout = QVBoxLayout(self.settings_inner)
        self.settings_layout.setContentsMargins(0, 0, 0, 0)
        self.settings_scroll.setWidget(self.settings_inner)
        layout.addWidget(self.settings_scroll, stretch=1)
        return page

    def build_settings_ui(self) -> None:
        while self.settings_layout.count():
            item = self.settings_layout.takeAt(0)
            if item.widget() is not None: item.widget().deleteLater()
        self.path_entries.clear()
        t = self._t()
        exe_installers = ("BCC", "Mocha_Pro", "Sapphire", "RedGiant", "RSMB")
        for p_data in self.app.plugins_data:
            p_name = p_data[0]
            if p_name in exe_installers or p_data[2] == "CUSTOM": continue
            row = QWidget(self.settings_inner)
            row.setObjectName("Card")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 8, 10, 8)
            lbl = QLabel(p_name, row)
            lbl.setMinimumWidth(120)
            row_layout.addWidget(lbl)
            edit = QLineEdit(self.app.custom_plugin_paths.get(p_name, ""), row)
            edit.textChanged.connect(lambda txt, n=p_name: self._save_single_path(n, txt))
            row_layout.addWidget(edit, stretch=1)
            self.path_entries[p_name] = edit
            btn_browse = QPushButton(t.get("browse", "Browse"), row)
            btn_browse.setObjectName("DarkButton")
            btn_browse.clicked.connect(lambda _c, n=p_name, e=edit: self._browse_plugin_path(n, e))
            row_layout.addWidget(btn_browse)
            btn_clear = QPushButton("✖", row)
            btn_clear.setStyleSheet(_DESTRUCTIVE_BTN_QSS)
            btn_clear.setFixedSize(30, 30)
            btn_clear.clicked.connect(lambda _c, e=edit: e.setText(""))
            row_layout.addWidget(btn_clear)
            self.settings_layout.addWidget(row)

    def _save_single_path(self, plugin_name: str, value: str) -> None:
        self.app.custom_plugin_paths[plugin_name] = value
        self.app.save_settings()

    def _browse_plugin_path(self, plugin_name: str, edit: QLineEdit) -> None:
        t = self._t()
        path = QFileDialog.getExistingDirectory(self, f"{t.get('select_folder', 'Select folder for')} {plugin_name}")
        if path:
            edit.setText(path)
            self._save_single_path(plugin_name, path)

    def reset_all_paths(self) -> None:
        t = self._t()
        reply = QMessageBox.question(self, t.get("reset_confirm_title", "Confirm"), t.get("reset_confirm_msg", "Reset all paths?"))
        if reply == QMessageBox.StandardButton.Yes:
            self.app.custom_plugin_paths.clear()
            for edit in self.path_entries.values(): edit.setText("")
            self.app.save_settings()

    # --- SYNC ---
    def _build_sync_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.lbl_sync_title = QLabel(self._t().get("sync_title", "Data Management"), page)
        self.lbl_sync_title.setObjectName("TitleLabel")
        layout.addWidget(self.lbl_sync_title)

        self.card_paths = QWidget(page)
        self.card_paths.setObjectName("Card")
        self.card_paths.setMaximumWidth(480)
        cp_layout = QVBoxLayout(self.card_paths)
        cp_layout.setContentsMargins(20, 15, 20, 20)
        self.lbl_sync_paths = QLabel(self._t().get("sync_paths", "Custom Installation Paths"), self.card_paths)
        cp_layout.addWidget(self.lbl_sync_paths)

        btns = QHBoxLayout()
        self.btn_export_paths = QPushButton(self._t().get("export_btn", "Export"), self.card_paths)
        self.btn_export_paths.setObjectName("DarkButton")
        self.btn_export_paths.clicked.connect(self.export_paths)
        btns.addWidget(self.btn_export_paths, stretch=1)
        self.btn_import_paths = QPushButton(self._t().get("import_btn", "Import"), self.card_paths)
        self.btn_import_paths.clicked.connect(self.import_paths)
        btns.addWidget(self.btn_import_paths, stretch=1)
        cp_layout.addLayout(btns)
        layout.addWidget(self.card_paths)

        self.card_plugins = QWidget(page)
        self.card_plugins.setObjectName("Card")
        self.card_plugins.setMaximumWidth(480)
        self.card_plugins_layout = QVBoxLayout(self.card_plugins)
        self.card_plugins_layout.setContentsMargins(20, 15, 20, 20)
        layout.addWidget(self.card_plugins)

        self.lbl_sync_warn = QLabel(self._t().get("sync_warn", "Note: Local files are not transferred."), page)
        self.lbl_sync_warn.setObjectName("DimLabel")
        layout.addWidget(self.lbl_sync_warn)
        layout.addStretch(1)
        return page

    def build_sync_ui(self) -> None:
        while self.card_plugins_layout.count():
            item = self.card_plugins_layout.takeAt(0)
            if item.widget() is not None: item.widget().deleteLater()
        t = self._t()
        lbl = QLabel(t.get("sync_custom", "Custom Plugins"), self.card_plugins)
        self.card_plugins_layout.addWidget(lbl)

        btns = QHBoxLayout()
        self.btn_export_custom = QPushButton(t.get("export_btn", "Export"), self.card_plugins)
        self.btn_export_custom.setObjectName("DarkButton")
        self.btn_export_custom.clicked.connect(self.export_custom)
        btns.addWidget(self.btn_export_custom, stretch=1)
        self.btn_import_custom = QPushButton(t.get("import_btn", "Import"), self.card_plugins)
        self.btn_import_custom.clicked.connect(self.import_custom)
        btns.addWidget(self.btn_import_custom, stretch=1)
        self.card_plugins_layout.addLayout(btns)

        list_scroll = QScrollArea(self.card_plugins)
        list_scroll.setWidgetResizable(True)
        list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        list_scroll.setMaximumHeight(140)
        list_inner = QWidget()
        list_layout = QVBoxLayout(list_inner)
        if os.path.exists(self.app.custom_configs_dir):
            for filename in os.listdir(self.app.custom_configs_dir):
                if not filename.endswith(".json"): continue
                row = QWidget(list_inner)
                row.setStyleSheet("background-color: #2a2a2a; border-radius: 6px;")
                row_layout = QHBoxLayout(row)
                fn_lbl = QLabel(filename, row)
                row_layout.addWidget(fn_lbl, stretch=1)
                btn_exp = QPushButton(t.get("export_btn", "Export"), row)
                btn_exp.setObjectName("DarkButton")
                btn_exp.clicked.connect(lambda _c, f=filename: self.export_specific_config(f))
                row_layout.addWidget(btn_exp)
                btn_del = QPushButton("✖", row)
                btn_del.setStyleSheet(_DELETE_X_BTN_QSS)
                btn_del.clicked.connect(lambda _c, f=filename: self.delete_config(f))
                row_layout.addWidget(btn_del)
                list_layout.addWidget(row)
        list_scroll.setWidget(list_inner)
        self.card_plugins_layout.addWidget(list_scroll)

    def export_paths(self) -> None:
        t = self._t()
        path, _ = QFileDialog.getSaveFileName(
            self,
            t.get("export_paths_title", "Export paths"),
            "paths.json",
            t.get("json_filter", "JSON files (*.json)"),
        )
        if not path: return
        with open(path, "w", encoding="utf-8") as f: json.dump(self.app.custom_plugin_paths, f, ensure_ascii=False, indent=4)

    def import_paths(self) -> None:
        t = self._t()
        path, _ = QFileDialog.getOpenFileName(
            self,
            t.get("import_paths_title", "Import paths"),
            "",
            t.get("json_filter", "JSON files (*.json)"),
        )
        if not path: return
        with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        if isinstance(data, dict):
            self.app.custom_plugin_paths.update(data)
            self.app.save_settings()
            self.build_settings_ui()

    def export_custom(self) -> None:
        t = self._t()
        path, _ = QFileDialog.getSaveFileName(
            self,
            t.get("export_custom_title", "Export all custom plugins"),
            "custom_plugins.json",
            t.get("json_filter", "JSON files (*.json)"),
        )
        if not path: return
        merged = {"plugins": []}
        if os.path.exists(self.app.custom_configs_dir):
            for filename in os.listdir(self.app.custom_configs_dir):
                if not filename.endswith(".json"): continue
                with open(os.path.join(self.app.custom_configs_dir, filename), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for p in data.get("plugins", []): merged["plugins"].append(p)
        with open(path, "w", encoding="utf-8") as f: json.dump(merged, f, ensure_ascii=False, indent=4)

    def import_custom(self) -> None:
        t = self._t()
        path, _ = QFileDialog.getOpenFileName(
            self,
            t.get("import_custom_title", "Import custom plugins"),
            "",
            t.get("json_filter", "JSON files (*.json)"),
        )
        if not path: return
        with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        if "plugins" not in data: return
        filename = os.path.basename(path)
        dest = os.path.join(self.app.custom_configs_dir, filename)
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(dest):
            dest = os.path.join(self.app.custom_configs_dir, f"{base}_{counter}{ext}")
            counter += 1
        shutil.copy2(path, dest)
        if hasattr(self.app, "reload_custom_plugins"): self.app.reload_custom_plugins()
        self.build_sync_ui()

    def export_specific_config(self, filename: str) -> None:
        t = self._t()
        src = os.path.join(self.app.custom_configs_dir, filename)
        path, _ = QFileDialog.getSaveFileName(
            self,
            t.get("export_config_title", "Export configuration"),
            filename,
            t.get("json_filter", "JSON files (*.json)"),
        )
        if path: shutil.copy2(src, path)

    def delete_config(self, filename: str) -> None:
        t = self._t()
        reply = QMessageBox.question(self, t.get("un_confirm_title", "Confirm"), f"{t.get('un_confirm_msg', 'Delete')} {filename}?")
        if reply == QMessageBox.StandardButton.Yes:
            os.remove(os.path.join(self.app.custom_configs_dir, filename))
            if hasattr(self.app, "reload_custom_plugins"): self.app.reload_custom_plugins()
            self.build_sync_ui()

    # --- UNINSTALL ---
    def _build_uninstall_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 30, 20, 20)
        layout.setSpacing(10)
        self.lbl_un_title = QLabel(self._t().get("un_title", "Uninstall Plugins"), page)
        self.lbl_un_title.setObjectName("TitleLabel")
        layout.addWidget(self.lbl_un_title, alignment=Qt.AlignmentFlag.AlignCenter)

        self.lbl_un_desc = QLabel(self._t().get("un_desc", ""), page)
        self.lbl_un_desc.setObjectName("DimLabel")
        layout.addWidget(self.lbl_un_desc, alignment=Qt.AlignmentFlag.AlignCenter)

        from install_tab import InstallTab  
        self.un_seg = SegmentedButton(InstallTab.AE_VERSIONS, page)
        self.un_seg.set_value(self.un_version, emit=False)
        self.un_seg.valueChanged.connect(self._on_un_version_changed)
        layout.addWidget(self.un_seg, alignment=Qt.AlignmentFlag.AlignCenter)

        self.un_scroll = QScrollArea(page)
        self.un_scroll.setWidgetResizable(True)
        self.un_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.un_inner = QWidget()
        self.un_layout = QVBoxLayout(self.un_inner)
        self.un_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.un_scroll.setWidget(self.un_inner)
        layout.addWidget(self.un_scroll, stretch=1)
        return page

    def _on_un_version_changed(self, value: str) -> None:
        self.un_version = value
        self.build_uninstall_ui()

    def build_uninstall_ui(self) -> None:
        while self.un_layout.count():
            item = self.un_layout.takeAt(0)
            if item.widget() is not None: item.widget().deleteLater()
        t = self._t()
        if self.un_version == "None":
            lbl = QLabel(t.get("un_select_ae", "Please select an AE version from the list above."), self.un_inner)
            lbl.setStyleSheet("color: #cc5555;")
            self.un_layout.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
            return

        full_ver = "20" + self.un_version
        is_installed = getattr(self.app, "is_plugin_installed", None)
        installed_any = False
        install_tab = getattr(self.app, "install_tab_widget", None)
        items = (install_tab.checkboxes if install_tab is not None else [])
        
        for name, _cb in sorted(items, key=lambda x: x[0].lower()):
            if is_installed is None: continue
            try:
                if not is_installed(name, full_ver): continue
            except Exception: continue
            installed_any = True
            row = QWidget(self.un_inner)
            row.setObjectName("Card")
            row_layout = QHBoxLayout(row)
            lbl = QLabel(name, row)
            row_layout.addWidget(lbl, stretch=1)
            btn_del = QPushButton(t.get("un_btn", "Delete"), row)
            btn_del.setStyleSheet("QPushButton { background-color: #882222; color: white; border-radius: 4px; padding: 4px 12px; font-weight: bold; outline: none; } QPushButton:hover { background-color: #aa3333; }")
            btn_del.clicked.connect(lambda _c, n=name, fv=full_ver: self.request_uninstall(n, fv))
            row_layout.addWidget(btn_del)
            self.un_layout.addWidget(row)

        if not installed_any:
            lbl = QLabel(t.get("un_none", "No plugins installed for this version."), self.un_inner)
            lbl.setObjectName("DimLabel")
            self.un_layout.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)

    def request_uninstall(self, plugin_name: str, full_ver: str) -> None:
        """[AKSIOM-FIX UI-16] uninstall_plugin может занять секунды (rmtree
        больших папок, winreg-операции). Запускаем в фоне; по завершению
        эмитим сигнал, который триггерит перерисовку в главном потоке."""
        t = self._t()
        reply = QMessageBox.question(self, t.get("un_confirm_title", "Confirm"), f"{t.get('un_confirm_msg', 'Uninstall')} {plugin_name}?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not hasattr(self.app, "uninstall_plugin"):
            return

        import threading
        # Лениво создаём сигнал-канал, если ещё не создан
        if not hasattr(self, "_uninstall_done_signal"):
            from PyQt6.QtCore import pyqtSignal, QObject

            class _UninstallSignals(QObject):
                done = pyqtSignal()

            self._uninstall_signals = _UninstallSignals()
            self._uninstall_signals.done.connect(self.build_uninstall_ui)
            self._uninstall_done_signal = self._uninstall_signals.done

        def _worker() -> None:
            try:
                self.app.uninstall_plugin(plugin_name, full_ver)
            except Exception as exc:  # noqa: BLE001
                print(f"uninstall_plugin: {exc}")
            self._uninstall_done_signal.emit()

        threading.Thread(target=_worker, daemon=True).start()

    # ==================================================================
    # PAGE: Misc (Прочее) + МАМБО РЕЖИМ
    # ==================================================================
    def _build_options_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 30, 20, 20)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        t = self._t()
        self.lbl_options_title = QLabel(t.get("options_title", "Misc Settings"), page)
        self.lbl_options_title.setObjectName("TitleLabel")
        layout.addWidget(self.lbl_options_title)

        self.cb_old_rsmb = QCheckBox(t.get("old_rsmb_lbl", "Old RSMB installer"), page)
        self.cb_old_rsmb.setChecked(self.app.old_rsmb)
        self.cb_old_rsmb.stateChanged.connect(self._on_old_rsmb_changed)
        layout.addWidget(self.cb_old_rsmb)

        # Единая галочка вместо прежних cb_rg_plugin_only / cb_rg_maxon_app.
        # Когда включена — в списке плагинов появляются Universe / Trapcode / MBS.
        # Стиль уменьшен (квадрат индикатора 14×14, шрифт 12pt) — чтобы она
        # не выглядела гигантской рядом с лаконичной cb_old_rsmb.
        self.cb_old_rg_mode = QCheckBox(
            t.get("old_rg_mode_lbl", "Old RedGiant mode (Universe / Trapcode / MBS)"),
            page,
        )
        self.cb_old_rg_mode.setChecked(self.app.old_rg_mode)
        self.cb_old_rg_mode.stateChanged.connect(self._on_old_rg_mode_changed)
        # Локальный QSS перекрывает глобальный (18×18). Цвет берём из COLOR_TEXT,
        # чтобы не отличался от соседних чекбоксов.
        self.cb_old_rg_mode.setStyleSheet(
            f"QCheckBox {{ color: {COLOR_TEXT}; spacing: 8px; font-size: 12px; }}"
            "QCheckBox::indicator { width: 14px; height: 14px; "
            "border: 1.5px solid #55555a; border-radius: 3px; "
            "background-color: transparent; }"
            f"QCheckBox::indicator:hover {{ border: 1.5px solid {COLOR_ACCENT}; }}"
            f"QCheckBox::indicator:checked {{ background-color: {COLOR_ACCENT}; "
            f"border: 1.5px solid {COLOR_ACCENT}; "
            f'background-image: url("{CHECKMARK_DATA_URL}"); '
            "background-position: center; background-repeat: no-repeat; }"
        )
        layout.addWidget(self.cb_old_rg_mode)

        # Кнопка ручного запуска активатора Maxon. Полезна, когда после установки
        # плагины Maxon не активировались автоматически — пользователь может
        # повторить шаг активации не переустанавливая весь плагин.
        self.btn_maxon_activation = QPushButton(
            t.get("maxon_activation_btn", "Run Maxon activation"), page,
        )
        self.btn_maxon_activation.clicked.connect(self._on_maxon_activation_clicked)
        self.btn_maxon_activation.setStyleSheet(
            "QPushButton { background-color: #2a2a2a; color: #e0e0e0; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 4px; "
            "padding: 6px 14px; }"
            "QPushButton:hover { background-color: #3a3a3a; }"
            "QPushButton:pressed { background-color: #1f1f1f; }"
        )

        # Кнопка явного сохранения настроек. Все изменения чекбоксов уже
        # сохраняются автоматически в _on_*_changed handlers, но эта кнопка
        # даёт пользователю явный контроль (и подтверждение «Сохранено»).
        # Дополнительно она перерисовывает фильтр плагинов, чтобы изменения
        # видимости Universe/Trapcode/MBS отразились немедленно.
        self.btn_save_settings = QPushButton(
            t.get("save_btn", "Сохранить"), page,
        )
        self.btn_save_settings.clicked.connect(self._on_save_settings_clicked)
        # [AKSIOM-FIX UI-13] :pressed раньше использовал #2a5a8a (синий!),
        # хотя палитра приложения фиолетовая (COLOR_ACCENT). Заменяем на
        # COLOR_ACCENT_HOV — оттенок одной палитры, кнопка не «прыгает» в синий.
        self.btn_save_settings.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_ACCENT}; color: white; "
            "border: none; border-radius: 4px; padding: 6px 14px; "
            "font-weight: 600; }}"
            f"QPushButton:hover {{ background-color: {COLOR_ACCENT_HOV}; }}"
            f"QPushButton:pressed {{ background-color: {COLOR_ACCENT_HOV}; }}"
        )

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 4, 0, 0)
        btn_row.setSpacing(8)
        btn_row.addWidget(self.btn_maxon_activation)
        btn_row.addWidget(self.btn_save_settings)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # Toast-индикатор «Сохранено» — скрыт по умолчанию, появляется
        # на 2 секунды после клика по кнопке Сохранить. Размещаем его прямо
        # под рядом кнопок, чтобы не сдвигать прочую вёрстку.
        self.lbl_save_toast = QLabel("", page)
        self.lbl_save_toast.setStyleSheet(
            "QLabel { color: #6dd66d; font-size: 12px; "
            "padding: 2px 0px; background: transparent; }"
        )
        self.lbl_save_toast.hide()
        layout.addWidget(self.lbl_save_toast)

        # ---------- МАМБО КНОПКА (Скрытая маскировка) ----------
        self.cb_mambo = QCheckBox(
            t.get("mambo_hw_accel", "Enable hardware UI acceleration"), page
        )
        self.cb_mambo.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 13px;")
        self.cb_mambo.stateChanged.connect(self._on_mambo_changed)
        layout.addWidget(self.cb_mambo)
        # -------------------------------------------------------

        self.drive_widget = QWidget(page)
        drive_layout = QVBoxLayout(self.drive_widget)
        drive_layout.setContentsMargins(0, 10, 0, 0)
        self.lbl_drive = QLabel(t.get("drive_lbl", "AE Installation Drive:"), self.drive_widget)
        drive_layout.addWidget(self.lbl_drive)
        drives = self._scan_drives()
        self.drive_seg = SegmentedButton(drives, self.drive_widget)
        initial_drive = self.app.ae_drive if self.app.ae_drive in drives else drives[0]
        self.drive_seg.set_value(initial_drive, emit=False)
        self.drive_seg.valueChanged.connect(self.change_ae_drive)
        drive_layout.addWidget(self.drive_seg, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.drive_widget)
        if len(drives) <= 1: self.drive_widget.hide()

        ae_path_widget = QWidget(page)
        ae_path_layout = QVBoxLayout(ae_path_widget)
        ae_path_layout.setContentsMargins(0, 10, 0, 0)
        self.lbl_ae_path = QLabel(
            t.get("ae_path_lbl", "After Effects install path:"), ae_path_widget
        )
        ae_path_layout.addWidget(self.lbl_ae_path)

        path_row = QHBoxLayout()
        self.ae_path_edit = QLineEdit(self.app.custom_install_path or "", ae_path_widget)
        path_row.addWidget(self.ae_path_edit, 1)
        self.btn_ae_browse = QPushButton(
            t.get("browse_ellipsis", "Browse…"), ae_path_widget
        )
        self.btn_ae_browse.setObjectName("DarkButton")
        self.btn_ae_browse.clicked.connect(self._on_ae_path_browse)
        path_row.addWidget(self.btn_ae_browse)
        ae_path_layout.addLayout(path_row)

        btn_row = QHBoxLayout()
        self.btn_ae_default = QPushButton(
            t.get("default_path_btn", "Default path"), ae_path_widget
        )
        self.btn_ae_default.setObjectName("DarkButton")
        self.btn_ae_default.clicked.connect(self._on_ae_path_default)
        btn_row.addWidget(self.btn_ae_default)
        self.btn_ae_save = QPushButton(t.get("save_btn", "Save"), ae_path_widget)
        self.btn_ae_save.clicked.connect(self._on_ae_path_save)
        btn_row.addWidget(self.btn_ae_save)
        btn_row.addStretch(1)
        ae_path_layout.addLayout(btn_row)
        layout.addWidget(ae_path_widget)

        sep = QFrame(page)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #2a2a2a; border: none; max-height: 2px;")
        layout.addWidget(sep)

        self.btn_clear_cache = QPushButton(
            t.get("clear_cache_btn", "Clear download cache"), page
        )
        self.btn_clear_cache.setStyleSheet(_DESTRUCTIVE_BTN_QSS)
        self.btn_clear_cache.clicked.connect(self.clear_app_cache)
        layout.addWidget(self.btn_clear_cache)
        layout.addStretch(1)
        return page

    # ==================================================================
    # ЛОГИКА РЕЖИМА МАМБО
    # ==================================================================
    def _on_mambo_changed(self, state: int) -> None:
        """Включает/выключает мамбо-режим.

        Новое поведение:
          - Фоновая музыка (mp3 на лупе) НЕ запускается.
          - Слайд-таймер с подложкой через QSS border-image НЕ запускается.
          - На каждый клик мыши играет mambo.wav и всплывает случайная
            pop-картинка (mambo_pop_*.jpg) с анимацией снизу-вверх.
        """
        try:
            is_mambo = (state != 0)
            self.is_mambo_active = is_mambo
            app_inst = QApplication.instance()

            if is_mambo:
                # Лениво создаём оверлей. Parent — главное окно (top-level),
                # чтобы картинка показывалась поверх всего UI, а не только
                # вкладки «Дополнительно».
                if self.mambo_pop is None:
                    host = self._mambo_overlay_host()
                    if host is not None:
                        self.mambo_pop = MamboPopOverlay(host)

                if app_inst is not None:
                    app_inst.installEventFilter(self.mambo_filter)

                # Лог: какой звуковой бэкенд активен. Пользователь увидит
                # это в журнале событий и сможет понять, играет ли звук вообще.
                player = getattr(self.mambo_filter, "_player", None)
                backend = player.backend if player is not None else "none"
                self._mambo_log(f"режим включён, sound backend = {backend}")
                if backend == "none":
                    self._mambo_log(
                        "звук недоступен — ни winsound, ни QSoundEffect, "
                        "ни pygame не смогли инициализироваться"
                    )
            else:
                if app_inst is not None:
                    app_inst.removeEventFilter(self.mambo_filter)
                if self.mambo_pop is not None:
                    self.mambo_pop.cancel()
                # Останавливаем звук, если он сейчас играет
                player = getattr(self.mambo_filter, "_player", None)
                if player is not None:
                    player.stop()
        except Exception as exc:  # noqa: BLE001
            # Режим декоративный — не критично, но залогируем
            self._mambo_log(f"_on_mambo_changed exception: {exc}")

    def _mambo_overlay_host(self) -> QWidget | None:
        """Возвращает виджет, поверх которого показывается pop-картинка.
        Им должно быть главное окно (или AdvancedWindow), а не сама вкладка."""
        # Поднимаемся по parent-цепочке до top-level QWidget
        w: QWidget | None = self
        while w is not None:
            if w.isWindow():
                return w
            w = w.parentWidget()
        # fallback — текущий виджет
        return self

    @staticmethod
    def _scan_drives() -> list[str]:
        drives = [f"{d}:" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:\\")]
        return drives if drives else ["C:"]

    def update_drive_widget(self) -> None:
        drives = self._scan_drives()
        self.drive_seg.set_values(drives)
        if self.app.ae_drive in drives: self.drive_seg.set_value(self.app.ae_drive, emit=False)
        else:
            self.drive_seg.set_value(drives[0], emit=False)
            self.change_ae_drive(drives[0])
        self.drive_widget.setVisible(len(drives) > 1)

    def _on_old_rsmb_changed(self, _state: int) -> None:
        self.app.old_rsmb = self.cb_old_rsmb.isChecked()
        self.app.save_app_config()
        if hasattr(self.app, "update_all_plugin_labels"): self.app.update_all_plugin_labels()

    def _on_old_rg_mode_changed(self, _state: int) -> None:
        self.app.old_rg_mode = self.cb_old_rg_mode.isChecked()
        self.app.save_app_config()
        # Перерисовать видимость плагинов Universe/Trapcode/MBS в списке установки.
        install_tab = getattr(self.app, "install_tab_widget", None)
        if install_tab is not None and hasattr(install_tab, "apply_old_rg_visibility"):
            install_tab.apply_old_rg_visibility()
        if hasattr(self.app, "update_all_plugin_labels"):
            self.app.update_all_plugin_labels()

    def _on_maxon_activation_clicked(self) -> None:
        """
        Запустить активатор Maxon из ранее распакованных архивов плагинов.
        Делегирует фактический поиск exe и запуск Popen в InstallerLogicMixin.
        """
        t = self._t()
        runner = getattr(self.app, "run_maxon_activator", None)
        if runner is None:
            QMessageBox.critical(
                self,
                t.get("err_title", "Error"),
                t.get("maxon_activation_not_found",
                      "Maxon activator not found."),
            )
            return

        # Лёгкая защита от двойного клика — отключаем кнопку на 1 сек.
        self.btn_maxon_activation.setEnabled(False)
        try:
            ok, message = runner()
        finally:
            QTimer.singleShot(1000, lambda: self.btn_maxon_activation.setEnabled(True))

        title = t.get("info_title", "Info") if ok else t.get("err_title", "Error")
        if hasattr(self.app, "log"):
            try:
                self.app.log(message, message)
            except Exception:  # noqa: BLE001
                pass
        if ok:
            QMessageBox.information(self, title, message)
        else:
            QMessageBox.warning(self, title, message)

    def _on_save_settings_clicked(self) -> None:
        """
        Явное «Сохранить» для страницы «Прочее». Хотя все изменения уже
        сохраняются мгновенно в handlers (_on_old_rsmb_changed и т.п.), эта
        кнопка нужна как:
          1) Психологический «commit» — пользователь видит подтверждение.
          2) Force-refresh: даже если сигнал stateChanged по какой-то причине
             не отстрелил, мы пересинхронизируем состояние с UI прямо сейчас.
          3) Перерисовка фильтра — Universe/Trapcode/MBS сразу видны/скрыты.
        """
        t = self._t()
        # Принудительно копируем состояние чекбоксов в self.app
        # (на случай если handler stateChanged по какой-то причине не сработал).
        try:
            self.app.old_rsmb = bool(self.cb_old_rsmb.isChecked())
            self.app.old_rg_mode = bool(self.cb_old_rg_mode.isChecked())
        except Exception as exc:  # noqa: BLE001
            print(f"_on_save_settings_clicked sync error: {exc}")

        # Записываем в app_config.json
        try:
            self.app.save_app_config()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                t.get("err_title", "Error"),
                f"{t.get('save_err', 'Save error')}: {exc}",
            )
            return

        # Перерисовать видимость плагинов в списке (учитывая старый RG режим).
        install_tab = getattr(self.app, "install_tab_widget", None)
        if install_tab is not None and hasattr(install_tab, "apply_old_rg_visibility"):
            try:
                install_tab.apply_old_rg_visibility()
            except Exception as exc:  # noqa: BLE001
                print(f"apply_old_rg_visibility failed: {exc}")
        # Обновить тексты меток (для суффиксов вроде [Old]).
        if hasattr(self.app, "update_all_plugin_labels"):
            try:
                self.app.update_all_plugin_labels()
            except Exception as exc:  # noqa: BLE001
                print(f"update_all_plugin_labels failed: {exc}")

        # Toast «Сохранено» на 2 секунды.
        self.lbl_save_toast.setText(
            "✓ " + t.get("save_ok", "Сохранено")
        )
        self.lbl_save_toast.show()
        QTimer.singleShot(2000, self.lbl_save_toast.hide)

    def _update_rg_maxon_visibility(self) -> None:
        # Метод оставлен для обратной совместимости (вызывался из старого UI).
        return None

    def change_ae_drive(self, value: str) -> None:
        self.app.ae_drive = value
        self.app.app_settings["ae_drive"] = value
        self.app.save_app_config()
        install_tab = getattr(self.app, "install_tab_widget", None)
        if install_tab is not None: install_tab.check_installed_plugins()

    @staticmethod
    def _detect_default_ae_path_local() -> str:
        import re
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        adobe_dir = os.path.join(pf, "Adobe")
        if not os.path.isdir(adobe_dir): return ""
        candidates: list[tuple[str, str]] = []
        try:
            for name in os.listdir(adobe_dir):
                full = os.path.join(adobe_dir, name)
                if not os.path.isdir(full): continue
                m = re.match(r"(?i)Adobe After Effects\s*(20\d{2})", name)
                if m: candidates.append((m.group(1), full))
        except OSError: return ""
        if not candidates: return ""
        candidates.sort(key=lambda p: p[0], reverse=True)
        base = candidates[0][1]
        plugins = os.path.join(base, "Support Files", "Plug-ins")
        return plugins if os.path.isdir(plugins) else base

    def _on_ae_path_browse(self) -> None:
        t = self._t()
        start_dir = (self.ae_path_edit.text().strip() or os.environ.get("ProgramFiles", r"C:\Program Files"))
        chosen = QFileDialog.getExistingDirectory(
            self, t.get("target_folder", "Select the Plug-ins folder"), start_dir
        )
        if chosen: self.ae_path_edit.setText(os.path.normpath(chosen))

    def _on_ae_path_default(self) -> None:
        self.ae_path_edit.setText(self._detect_default_ae_path_local())

    def _on_ae_path_save(self) -> None:
        t = self._t()
        new_path = self.ae_path_edit.text().strip()
        if new_path:
            new_path = os.path.normpath(new_path)
            if not os.path.isdir(new_path):
                QMessageBox.warning(
                    self,
                    t.get("warn_title", "Warning"),
                    t.get("folder_not_exist", "The specified folder does not exist:") + "\n" + new_path,
                )
                return

        self.app.custom_install_path = new_path
        self.app.app_settings["custom_install_path"] = new_path
        self.app.app_settings["ae_path_configured"] = True
        self.app.save_app_config()

        install_tab = getattr(self.app, "install_tab_widget", None)
        if install_tab is not None and hasattr(install_tab, "check_installed_plugins"):
            try: install_tab.check_installed_plugins()
            except Exception as exc: print(f"check_installed_plugins after AE-path save: {exc}")

        QMessageBox.information(
            self,
            t.get("ae_path_saved_title", "Done"),
            t.get("ae_path_saved_msg", "After Effects install path saved.\nInstalled plugins list refreshed."),
        )

    def clear_app_cache(self) -> None:
        """[AKSIOM-FIX #20] Один проход через os.scandir вместо os.walk + rmtree
        дважды по тем же файлам. Манифесты installed/ теперь тоже сохраняются."""
        t = self._t()
        msg = t.get(
            "clear_cache_confirm",
            "Delete all temporary files and downloaded archives?\nThis cannot be undone.",
        )
        reply = QMessageBox.question(self, t.get("warn_title", "Warning"), msg)
        if reply != QMessageBox.StandardButton.Yes:
            return

        keep_files = {"app_config.json", "settings.json", "plugins.json", "lang.json"}
        # [AKSIOM-FIX #20] installed/ — манифесты установленных плагинов,
        # их сносить = терять информацию для корректного uninstall.
        keep_dirs = {"custom_configs", "installed"}
        deleted_size = 0

        def _dir_size(path: str) -> int:
            """Один проход для подсчёта размера через os.scandir (быстрее os.walk)."""
            total = 0
            try:
                for entry in os.scandir(path):
                    try:
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            total += _dir_size(entry.path)
                    except OSError:
                        continue
            except OSError:
                pass
            return total

        try:
            for item in os.listdir(self.app.cache_dir):
                item_path = os.path.join(self.app.cache_dir, item)
                try:
                    if os.path.isfile(item_path):
                        if item not in keep_files:
                            deleted_size += os.path.getsize(item_path)
                            os.remove(item_path)
                    elif os.path.isdir(item_path):
                        if item not in keep_dirs:
                            deleted_size += _dir_size(item_path)
                            shutil.rmtree(item_path, ignore_errors=True)
                except OSError:
                    continue
            mb = deleted_size / (1024 * 1024)
            success_tpl = t.get(
                "clear_cache_success",
                "Cache cleared successfully!\nFreed: {mb:.2f} MB",
            )
            QMessageBox.information(
                self, t.get("info_title", "Info"), success_tpl.format(mb=mb),
            )
        except Exception as exc:
            err_tpl = t.get("clear_cache_error", "An error occurred:\n{err}")
            QMessageBox.critical(
                self,
                t.get("err_title", "Error"),
                err_tpl.format(err=exc),
            )

    def retranslate(self) -> None:
        t = self._t()
        for pid, label in (
            ("changelog", t.get("tab_changelog", "Changelog")),
            ("logs", t.get("tab_logs", "Logs")),
            ("custom", t.get("tab_custom", "Custom Plugins")),
            ("settings", t.get("tab_settings", "Individual Paths")),
            ("sync", t.get("tab_sync", "Export / Import")),
            ("uninstall", t.get("tab_uninstall", "Uninstall")),
            ("options", t.get("tab_options", "Misc")),
        ):
            self.sidebar_btns[pid].setText(label)

        self.changelog_text.setPlainText(self.app.CHANGELOG_TEXT.get(self.app.current_lang, ""))

        if hasattr(self, "btn_export_logs"): self.btn_export_logs.setText(t.get("export_log_btn", "Export Logs"))
        if hasattr(self, "lbl_settings_title"):
            self.lbl_settings_title.setText(t.get("settings_title", "Individual Paths"))
            self.btn_reset_all.setText(t.get("reset_all", "Reset All"))
        if hasattr(self, "lbl_sync_title"):
            self.lbl_sync_title.setText(t.get("sync_title", "Data Management"))
            self.lbl_sync_paths.setText(t.get("sync_paths", "Custom Installation Paths"))
            self.btn_export_paths.setText(t.get("export_btn", "Export"))
            self.btn_import_paths.setText(t.get("import_btn", "Import"))
            self.lbl_sync_warn.setText(t.get("sync_warn", "Note: Local files are not transferred."))
        if hasattr(self, "lbl_un_title"):
            self.lbl_un_title.setText(t.get("un_title", "Uninstall Plugins"))
            self.lbl_un_desc.setText(t.get("un_desc", ""))
        if hasattr(self, "lbl_options_title"):
            self.lbl_options_title.setText(t.get("options_title", "Misc Settings"))
            self.cb_old_rsmb.setText(t.get("old_rsmb_lbl", "Old RSMB installer"))
            self.cb_old_rg_mode.setText(
                t.get("old_rg_mode_lbl", "Old RedGiant mode (Universe / Trapcode / MBS)")
            )
            self.btn_maxon_activation.setText(
                t.get("maxon_activation_btn", "Run Maxon activation")
            )
            self.btn_save_settings.setText(t.get("save_btn", "Save"))
            self.lbl_drive.setText(t.get("drive_lbl", "AE Installation Drive:"))
            self.btn_clear_cache.setText(
                t.get("clear_cache_btn", "Clear download cache")
            )
            # [AKSIOM-FIX 2026-05] AE-path виджеты и cb_mambo раньше брали
            # язык только из self.app.current_lang в момент создания и
            # никогда не обновлялись при переключении языка на лету.
            if hasattr(self, "cb_mambo"):
                self.cb_mambo.setText(
                    t.get("mambo_hw_accel", "Enable hardware UI acceleration")
                )
            if hasattr(self, "lbl_ae_path"):
                self.lbl_ae_path.setText(
                    t.get("ae_path_lbl", "After Effects install path:")
                )
            if hasattr(self, "btn_ae_browse"):
                self.btn_ae_browse.setText(
                    t.get("browse_ellipsis", "Browse…")
                )
            if hasattr(self, "btn_ae_default"):
                self.btn_ae_default.setText(
                    t.get("default_path_btn", "Default path")
                )
            if hasattr(self, "btn_ae_save"):
                self.btn_ae_save.setText(t.get("save_btn", "Save"))

        if hasattr(self, "btn_new_custom"):
            self.btn_new_custom.setText(t.get("c_new_btn", "+ New Plugin"))

        current = self.stack.currentIndex()
        if current == self._page_index["custom"]: self.build_custom_ui(self.current_editing_plugin)
        elif current == self._page_index["settings"]: self.build_settings_ui()
        elif current == self._page_index["sync"]: self.build_sync_ui()
        elif current == self._page_index["uninstall"]: self.build_uninstall_ui()

    @staticmethod
    def _dim_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 12px;")
        return lbl