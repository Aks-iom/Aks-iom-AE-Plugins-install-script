# -*- coding: utf-8 -*-
"""registry.py — ImportReg, SetRegValue, EnableCepDebug.

[AKSIOM-FIX #21] Удалён неиспользуемый импорт ctypes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

from core.installer.manifest import (
    ARTIFACT_EXE_INSTALL,
    ARTIFACT_REG_VALUE,
    Artifact,
)
from core.installer.steps.base import InstallStep, StepResult

if TYPE_CHECKING:
    from core.installer.context import InstallContext


CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _resolve_hive(hive_str: str):
    if sys.platform != "win32":
        raise RuntimeError("Registry steps are Windows-only")
    import winreg  # type: ignore
    return {
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
        "HKCU": winreg.HKEY_CURRENT_USER,
    }[hive_str]


def _resolve_value_type(type_str: str):
    if sys.platform != "win32":
        raise RuntimeError("Registry steps are Windows-only")
    import winreg  # type: ignore
    return {
        "REG_SZ": winreg.REG_SZ,
        "REG_DWORD": winreg.REG_DWORD,
        "REG_EXPAND_SZ": winreg.REG_EXPAND_SZ,
    }[type_str]


# ===========================================================================
# import_reg
# ===========================================================================
class ImportRegStep(InstallStep):
    """JSON: {"type": "import_reg", "path": "{SRC_DIR}/keys.reg"}"""

    def __init__(self, path: str) -> None:
        self.path = path

    @classmethod
    def from_dict(cls, data: dict) -> "ImportRegStep":
        return cls(path=data["path"])

    def execute(self, context: "InstallContext") -> StepResult:
        artifacts: list[Artifact] = []
        try:
            reg_file = context.expand(self.path)
            if not os.path.exists(reg_file):
                return StepResult(False, artifacts, f"import_reg: file not found: {reg_file}")
            if sys.platform != "win32":
                return StepResult(False, artifacts, "import_reg: Windows-only")

            try:
                proc = subprocess.run(
                    ["reg.exe", "import", reg_file],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                return StepResult(False, artifacts, "import_reg: reg.exe timed out")

            if proc.returncode != 0:
                err = (proc.stderr or b"").decode("cp1251", errors="replace").strip()
                return StepResult(
                    False, artifacts,
                    f"import_reg: reg.exe exit {proc.returncode}: {err}",
                )

            artifacts.append(Artifact(
                type=ARTIFACT_EXE_INSTALL,
                path=reg_file,
                extra={"kind": "reg_import"},
            ))
            context.log(
                f"   ✓ Импортирован .reg-файл: {reg_file}",
                f"   ✓ Imported .reg file: {reg_file}",
            )
            return StepResult(True, artifacts)
        except Exception as exc:  # noqa: BLE001
            return StepResult(False, artifacts, f"import_reg failed: {exc}")


# ===========================================================================
# set_reg_value
# ===========================================================================
class SetRegValueStep(InstallStep):
    """
    JSON:
        {
          "type": "set_reg_value",
          "hive": "HKLM",
          "key": "Software\\Adobe\\CSXS.11",
          "name": "PlayerDebugMode",
          "value": "1",
          "value_type": "REG_SZ",
          "wow64": true
        }
    """

    def __init__(
        self,
        hive: str,
        key: str,
        name: str,
        value,
        value_type: str = "REG_SZ",
        wow64: bool = False,
    ) -> None:
        self.hive = hive
        self.key = key
        self.name = name
        self.value = value
        self.value_type = value_type
        self.wow64 = wow64

    @classmethod
    def from_dict(cls, data: dict) -> "SetRegValueStep":
        value_type = data.get("value_type") or data.get("reg_type") or "REG_SZ"
        return cls(
            hive=data["hive"],
            key=data["key"],
            name=data["name"],
            value=data.get("value"),
            value_type=value_type,
            wow64=bool(data.get("wow64", False)),
        )

    def execute(self, context: "InstallContext") -> StepResult:
        artifacts: list[Artifact] = []
        if sys.platform != "win32":
            return StepResult(False, artifacts, "set_reg_value: Windows-only")
        try:
            import winreg  # type: ignore
            hive = _resolve_hive(self.hive)
            access = winreg.KEY_WRITE
            if self.wow64:
                access |= winreg.KEY_WOW64_64KEY

            value_type_const = _resolve_value_type(self.value_type)
            value = self.value
            if self.value_type == "REG_DWORD":
                if value is None:
                    return StepResult(False, artifacts, "set_reg_value: REG_DWORD value is None")
                try:
                    value = int(value)
                except (TypeError, ValueError) as exc:
                    return StepResult(False, artifacts, f"set_reg_value: REG_DWORD invalid: {exc}")
            elif self.value_type in ("REG_SZ", "REG_EXPAND_SZ"):
                if value is None:
                    return StepResult(False, artifacts, f"set_reg_value: {self.value_type} value is None")
                value = str(value)

            with winreg.CreateKeyEx(hive, self.key, 0, access) as k:
                winreg.SetValueEx(k, self.name, 0, value_type_const, value)

            full_path = f"{self.hive}\\{self.key}\\{self.name}"
            artifacts.append(Artifact(
                type=ARTIFACT_REG_VALUE,
                path=full_path,
                extra={"wow64": self.wow64},
            ))
            context.log(
                f"   ✓ Запись в реестр: {full_path} = {value}",
                f"   ✓ Registry write: {full_path} = {value}",
            )
            return StepResult(True, artifacts)
        except Exception as exc:  # noqa: BLE001
            return StepResult(False, artifacts, f"set_reg_value failed: {exc}")


# ===========================================================================
# enable_cep_debug
# ===========================================================================
class EnableCepDebugStep(InstallStep):
    """JSON: {"type": "enable_cep_debug"}"""

    def __init__(self) -> None:
        pass

    @classmethod
    def from_dict(cls, data: dict) -> "EnableCepDebugStep":
        return cls()

    def execute(self, context: "InstallContext") -> StepResult:
        artifacts: list[Artifact] = []
        if sys.platform != "win32":
            return StepResult(False, artifacts, "enable_cep_debug: Windows-only")
        try:
            import winreg  # type: ignore
            access = winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
            success_count = 0
            for csxs in ("CSXS.10", "CSXS.11", "CSXS.12", "CSXS.13",
                         "CSXS.14", "CSXS.15", "CSXS.16"):
                key = f"Software\\Adobe\\{csxs}"
                try:
                    with winreg.CreateKeyEx(
                        winreg.HKEY_LOCAL_MACHINE, key, 0, access
                    ) as k:
                        winreg.SetValueEx(k, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
                    artifacts.append(Artifact(
                        type=ARTIFACT_REG_VALUE,
                        path=f"HKLM\\{key}\\PlayerDebugMode",
                        extra={"wow64": True},
                    ))
                    success_count += 1
                except OSError as exc:
                    context.log(
                        f"   ! CSXS не доступен: {csxs} ({exc})",
                        f"   ! CSXS unreachable: {csxs} ({exc})",
                    )
            if success_count == 0:
                return StepResult(False, artifacts, "enable_cep_debug: no CSXS keys")
            context.log(
                f"   ✓ CEP debug включён для {success_count} веток CSXS",
                f"   ✓ CEP debug enabled for {success_count} CSXS branches",
            )
            return StepResult(True, artifacts)
        except Exception as exc:  # noqa: BLE001
            return StepResult(False, artifacts, f"enable_cep_debug failed: {exc}")
