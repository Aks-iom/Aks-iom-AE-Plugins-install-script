# -*- coding: utf-8 -*-
"""
detector.py
Detector — выполняет detect-блоки из plugins.json.

Поддерживаемые типы:
  file_exists, dir_exists (+non_empty), reg_value_exists, glob_match,
  any_of, all_of.
"""

from __future__ import annotations

import glob
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.installer.context import InstallContext


class Detector:
    """Stateless. Используется через статический evaluate()."""

    @staticmethod
    def evaluate(detect: list[dict] | None, context: "InstallContext") -> bool:
        """
        Список detect-условий. По умолчанию — AND (все должны быть True).
        Если хотите OR — оборачивайте в {"type": "any_of", ...}.
        """
        if not detect:
            return False
        for cond in detect:
            if not Detector._eval_one(cond, context):
                return False
        return True

    # ------------------------------------------------------------------
    # Одно условие
    # ------------------------------------------------------------------
    @staticmethod
    def _eval_one(cond: dict, context: "InstallContext") -> bool:
        if not isinstance(cond, dict):
            return False
        ctype = cond.get("type")

        if ctype == "file_exists":
            return os.path.exists(context.expand(cond.get("path", "")))

        if ctype == "dir_exists":
            path = context.expand(cond.get("path", ""))
            if not os.path.isdir(path):
                return False
            if cond.get("non_empty"):
                try:
                    with os.scandir(path) as it:
                        return any(True for _ in it)
                except OSError:
                    return False
            return True

        if ctype == "reg_value_exists":
            if sys.platform != "win32":
                return False
            return Detector._reg_value_exists(
                cond.get("hive", ""),
                cond.get("key", ""),
                cond.get("name", ""),
                bool(cond.get("wow64", False)),
            )

        if ctype == "glob_match":
            pattern = context.expand(cond.get("pattern", ""))
            return bool(glob.glob(pattern))

        if ctype == "any_of":
            for sub in cond.get("conditions", []):
                if Detector._eval_one(sub, context):
                    return True
            return False

        if ctype == "all_of":
            subs = cond.get("conditions", [])
            if not subs:
                return False
            for sub in subs:
                if not Detector._eval_one(sub, context):
                    return False
            return True

        # неизвестный тип — считаем False
        return False

    @staticmethod
    def _reg_value_exists(hive_str: str, key: str, name: str, wow64: bool) -> bool:
        try:
            import winreg  # type: ignore
            hive_map = {
                "HKLM": winreg.HKEY_LOCAL_MACHINE,
                "HKCU": winreg.HKEY_CURRENT_USER,
            }
            hive = hive_map.get(hive_str)
            if hive is None:
                return False
            access = winreg.KEY_READ
            if wow64:
                access |= winreg.KEY_WOW64_64KEY
            try:
                with winreg.OpenKey(hive, key, 0, access) as k:
                    try:
                        winreg.QueryValueEx(k, name)
                        return True
                    except FileNotFoundError:
                        return False
            except FileNotFoundError:
                return False
            except OSError:
                return False
        except Exception:  # noqa: BLE001
            return False
