# -*- coding: utf-8 -*-
"""
manifest.py
Артефакты и InstalledManifest — запись/чтение/удаление.

[AKSIOM-FIX #2] Корректное удаление REG_KEY с поддержкой подключей через
DeleteKeyEx (winreg) и без хака с __dummy.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field

ARTIFACT_FILE = "file"
ARTIFACT_DIR = "dir"
ARTIFACT_REG_VALUE = "reg_value"
ARTIFACT_REG_KEY = "reg_key"
ARTIFACT_EXE_INSTALL = "exe_install"

SOURCE_MANAGED = "managed"
SOURCE_LEGACY = "legacy"


@dataclass
class Artifact:
    type: str
    path: str
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Artifact":
        return cls(
            type=data.get("type", ""),
            path=data.get("path", ""),
            extra=data.get("extra", {}) or {},
        )


def _split_reg_path_value(reg_path: str) -> tuple[str, str, str]:
    """
    Для REG_VALUE: 'HKLM\\Software\\X\\ValueName' → ('HKLM', 'Software\\X', 'ValueName')
    """
    parts = reg_path.split("\\")
    if len(parts) < 2:
        return parts[0] if parts else "", "", ""
    hive = parts[0]
    name = parts[-1]
    key = "\\".join(parts[1:-1])
    return hive, key, name


def _split_reg_path_key(reg_path: str) -> tuple[str, str]:
    """
    Для REG_KEY: 'HKLM\\Software\\X\\Sub' → ('HKLM', 'Software\\X\\Sub')
    [AKSIOM-FIX #2] Без хака с __dummy.
    """
    parts = reg_path.split("\\")
    if len(parts) < 1:
        return "", ""
    hive = parts[0]
    key = "\\".join(parts[1:])
    return hive, key


# Совместимость со старым именем (используется в pipeline.py / других местах).
_split_reg_path = _split_reg_path_value


def _delete_reg_key_recursive(hive, key: str, wow64: bool = False) -> bool:
    """
    [AKSIOM-FIX #2] Рекурсивно удаляет ключ реестра вместе с подключами.
    winreg.DeleteKey удаляет только пустой ключ, поэтому надо обходить дерево.
    На Windows 7+ можно использовать DeleteKeyEx с флагом view, но он также
    не удаляет подключи — рекурсия всё равно нужна.
    """
    if sys.platform != "win32":
        return False
    import winreg  # type: ignore

    access = winreg.KEY_READ | winreg.KEY_WRITE
    if wow64:
        access |= winreg.KEY_WOW64_64KEY

    # Сначала рекурсивно удаляем все подключи
    try:
        with winreg.OpenKey(hive, key, 0, access) as parent:
            subkeys: list[str] = []
            i = 0
            while True:
                try:
                    subkeys.append(winreg.EnumKey(parent, i))
                    i += 1
                except OSError:
                    break
            for sub in subkeys:
                _delete_reg_key_recursive(hive, f"{key}\\{sub}", wow64)
    except FileNotFoundError:
        return True  # уже нет — желаемое состояние достигнуто
    except OSError:
        return False

    # Теперь удаляем сам пустой ключ
    try:
        if hasattr(winreg, "DeleteKeyEx") and wow64:
            winreg.DeleteKeyEx(hive, key, winreg.KEY_WOW64_64KEY)
        else:
            winreg.DeleteKey(hive, key)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def remove_artifact(artifact: Artifact, *, ignore_errors: bool = True) -> bool:
    """Удаляет артефакт. Для exe_install — только логически (true)."""
    try:
        if artifact.type == ARTIFACT_FILE:
            if os.path.exists(artifact.path):
                try:
                    os.chmod(artifact.path, 0o666)
                except OSError:
                    pass
                os.remove(artifact.path)
            return True

        if artifact.type == ARTIFACT_DIR:
            if os.path.exists(artifact.path):
                shutil.rmtree(artifact.path, ignore_errors=ignore_errors)
            return True

        if artifact.type == ARTIFACT_REG_VALUE:
            if sys.platform != "win32":
                return True
            import winreg  # type: ignore
            hive_str, key, name = _split_reg_path_value(artifact.path)
            hive_map = {
                "HKLM": winreg.HKEY_LOCAL_MACHINE,
                "HKCU": winreg.HKEY_CURRENT_USER,
            }
            hive = hive_map.get(hive_str)
            if hive is None:
                return False
            access = winreg.KEY_WRITE
            if artifact.extra.get("wow64"):
                access |= winreg.KEY_WOW64_64KEY
            try:
                with winreg.OpenKey(hive, key, 0, access) as k:
                    winreg.DeleteValue(k, name)
                return True
            except FileNotFoundError:
                return True
            except OSError:
                return False

        if artifact.type == ARTIFACT_REG_KEY:
            if sys.platform != "win32":
                return True
            import winreg  # type: ignore
            # [AKSIOM-FIX #2] Корректное удаление без хака
            hive_str, key = _split_reg_path_key(artifact.path)
            if not key:
                return False
            hive_map = {
                "HKLM": winreg.HKEY_LOCAL_MACHINE,
                "HKCU": winreg.HKEY_CURRENT_USER,
            }
            hive = hive_map.get(hive_str)
            if hive is None:
                return False
            return _delete_reg_key_recursive(
                hive, key, wow64=bool(artifact.extra.get("wow64"))
            )

        if artifact.type == ARTIFACT_EXE_INSTALL:
            return True

    except Exception:  # noqa: BLE001
        if not ignore_errors:
            raise
        return False

    return False


class InstalledManifest:
    """Хранит и читает манифесты установок."""

    @staticmethod
    def _safe_name(name: str) -> str:
        return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)

    @classmethod
    def file_path(cls, installed_dir: str, plugin_name: str, ae_version: str) -> str:
        fn = f"{cls._safe_name(plugin_name)}__{cls._safe_name(ae_version)}.json"
        return os.path.join(installed_dir, fn)

    @classmethod
    def write(
        cls,
        installed_dir: str,
        plugin_name: str,
        ae_version: str,
        plugin_meta: dict,
        artifacts: list[Artifact],
        source: str = SOURCE_MANAGED,
    ) -> str:
        os.makedirs(installed_dir, exist_ok=True)
        path = cls.file_path(installed_dir, plugin_name, ae_version)
        data = {
            "plugin": plugin_name,
            "ae_version": ae_version,
            "installed_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "version": plugin_meta.get("version", ""),
            "source": source,
            "artifacts": [a.to_dict() for a in artifacts],
        }
        try:
            # Атомарная запись: пишем в .tmp, потом os.replace
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError as exc:
            print(f"InstalledManifest.write({plugin_name}): {exc}")
        return path

    @classmethod
    def read(
        cls, installed_dir: str, plugin_name: str, ae_version: str
    ) -> dict | None:
        path = cls.file_path(installed_dir, plugin_name, ae_version)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"InstalledManifest.read({plugin_name}): {exc}")
            return None

    @classmethod
    def delete(cls, installed_dir: str, plugin_name: str, ae_version: str) -> bool:
        path = cls.file_path(installed_dir, plugin_name, ae_version)
        if not os.path.exists(path):
            return True
        try:
            os.remove(path)
            return True
        except OSError as exc:
            print(f"InstalledManifest.delete({plugin_name}): {exc}")
            return False

    @classmethod
    def artifacts_present(cls, manifest_data: dict) -> bool:
        """Быстрая проверка: все ли артефакты из манифеста ещё существуют?"""
        for raw in manifest_data.get("artifacts", []):
            art = Artifact.from_dict(raw)
            if art.type == ARTIFACT_FILE:
                if not os.path.exists(art.path):
                    return False
            elif art.type == ARTIFACT_DIR:
                if not os.path.exists(art.path):
                    return False
                if art.extra.get("non_empty"):
                    try:
                        with os.scandir(art.path) as it:
                            if not any(True for _ in it):
                                return False
                    except OSError:
                        return False
            elif art.type == ARTIFACT_REG_VALUE:
                if sys.platform != "win32":
                    continue
                import winreg  # type: ignore
                hive_str, key, name = _split_reg_path_value(art.path)
                hive_map = {
                    "HKLM": winreg.HKEY_LOCAL_MACHINE,
                    "HKCU": winreg.HKEY_CURRENT_USER,
                }
                hive = hive_map.get(hive_str)
                if hive is None:
                    continue
                access = winreg.KEY_READ
                if art.extra.get("wow64"):
                    access |= winreg.KEY_WOW64_64KEY
                try:
                    with winreg.OpenKey(hive, key, 0, access) as k:
                        try:
                            winreg.QueryValueEx(k, name)
                        except FileNotFoundError:
                            return False
                except FileNotFoundError:
                    return False
                except OSError:
                    continue
        return True
