# -*- coding: utf-8 -*-
"""
context.py
InstallContext — состояние установки: версия AE, пути, опции, логгер.
Поддерживает подстановку шаблонов вида {VAR} и динамическую замену
'After Effects 20XX' → актуальной версии.

[AKSIOM-FIX #9] logger использует default_factory вместо unsafe lambda-default.
[AKSIOM-FIX #1] Добавлен опциональный self.transaction — шаги вроде copy_dir
могут регистрировать pending backups через context.transaction.register_backup().
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Callable


_AE_VERSION_RE = re.compile(r"(?i)(After Effects\s*)20\d{2}")


def _noop_logger(_ru: str, _en: str) -> None:
    """Default logger — no-op. Используется как default_factory."""
    return None


def _get_user_docs() -> str:
    """Возвращает путь к папке Документы текущего пользователя (Windows)."""
    if sys.platform != "win32":
        return os.path.expanduser("~/Documents")
    try:
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
        return buf.value
    except Exception:  # noqa: BLE001
        return os.path.expanduser("~/Documents")


def build_default_paths(
    ae_version: str,
    ae_drive: str = "",
    custom_install_path: str = "",
) -> dict[str, str]:
    """
    Строит словарь системных путей с учётом выбранного диска и custom AE-пути.
    Возвращает значения для всех {VAR}, поддерживаемых InstallContext.expand().
    """
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    if ae_drive:
        pf = ae_drive + os.path.splitdrive(pf)[1]
        pf86 = ae_drive + os.path.splitdrive(pf86)[1]

    pd = os.environ.get("ProgramData", r"C:\ProgramData")

    cip = (custom_install_path or "").strip()
    if cip and ae_version != "None":
        cip = _AE_VERSION_RE.sub(rf"\g<1>{ae_version}", cip)

    base_dir = (
        cip
        if cip
        else os.path.join(pf, "Adobe", f"Adobe After Effects {ae_version}")
    )

    plugins_dir = (
        os.path.join(base_dir, "Support Files", "Plug-ins")
        if not cip
        else cip
    )
    scripts_dir = (
        os.path.join(base_dir, "Support Files", "Scripts", "ScriptUI Panels")
        if not cip
        else os.path.join(cip, "Scripts", "ScriptUI Panels")
    )

    return {
        "PF": pf,
        "PF86": pf86,
        "PROGRAMDATA": pd,
        "AE_VERSION": ae_version,
        "AE_BASE": base_dir,
        "PLUGINS_DIR": plugins_dir,
        "SCRIPTS_DIR": scripts_dir,
        "COMMON_PLUGINS": os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore"),
        "CEP_EXTENSIONS": os.path.join(pf86, "Common Files", "Adobe", "CEP", "extensions"),
        "USER_DOCS": _get_user_docs(),
    }


@dataclass
class InstallContext:
    """
    Контекст одной установки. Все шаги принимают его как единственный параметр.
    """

    plugin_name: str
    ae_version: str
    src_dir: str
    paths: dict[str, str]
    custom_path: str | None = None
    options: dict = field(default_factory=dict)
    # [AKSIOM-FIX #9] default_factory вместо unsafe lambda-default
    logger: Callable[[str, str], None] = field(default=_noop_logger)
    # [AKSIOM-FIX #1] Опциональная ссылка на текущую транзакцию.
    # PluginInstaller.engine выставляет её перед циклом шагов, чтобы
    # шаги могли регистрировать pending backups (см. CopyDirStep replace).
    transaction: Any = field(default=None, repr=False)

    def expand(self, template: str | None) -> str:
        """{VAR} → реальное значение, плюс глобальная замена 'After Effects 20XX'."""
        if not template:
            return ""

        local: dict[str, str] = {
            "SRC_DIR": self.src_dir or "",
            "CUSTOM_PATH": self.custom_path or "",
        }
        merged = {**self.paths, **local}

        def repl(match: re.Match) -> str:
            key = match.group(1)
            return merged.get(key, match.group(0))

        result = re.sub(r"\{([A-Z_][A-Z0-9_]*)\}", repl, template)

        if self.ae_version and self.ae_version != "None":
            result = _AE_VERSION_RE.sub(rf"\g<1>{self.ae_version}", result)

        return result

    def get_option(self, dotted: str) -> bool:
        """Получить булево значение по пути 'options.old_rsmb'."""
        if not dotted:
            return False
        parts = dotted.split(".")
        if parts[0] == "options":
            parts = parts[1:]
        cur: object = self.options
        for p in parts:
            if isinstance(cur, dict):
                cur = cur.get(p)
            else:
                return False
        return bool(cur)

    def log(self, ru: str, en: str | None = None) -> None:
        """Удобный шорткат для шагов: ctx.log('...', '...')."""
        if en is None:
            en = ru
        try:
            self.logger(ru, en)
        except Exception:  # noqa: BLE001
            pass
