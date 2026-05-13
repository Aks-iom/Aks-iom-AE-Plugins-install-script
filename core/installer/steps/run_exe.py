# -*- coding: utf-8 -*-
"""run_exe.py — запуск .exe-инсталлера."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from core.installer.manifest import ARTIFACT_EXE_INSTALL, Artifact
from core.installer.steps.base import InstallStep, StepResult

if TYPE_CHECKING:
    from core.installer.context import InstallContext


CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class RunExeStep(InstallStep):
    """
    JSON:
        {
          "type": "run_exe",
          "path": "{SRC_DIR}/Setup.exe",
          "args": ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
          "wait": true,
          "ignore_codes": [3010]
        }

    Артефакт: ARTIFACT_EXE_INSTALL (без возможности отката — пользователь
    должен сносить через «Программы и компоненты»). Откат для exe_install
    в transaction.py пишет предупреждение и не пытается удалять.
    """

    def __init__(
        self,
        path: str,
        args: list[str] | None = None,
        wait: bool = True,
        ignore_codes: list[int] | None = None,
    ) -> None:
        self.path = path
        self.args = list(args or [])
        self.wait = wait
        self.ignore_codes = set(ignore_codes or [])

    @classmethod
    def from_dict(cls, data: dict) -> "RunExeStep":
        return cls(
            path=data["path"],
            args=data.get("args", []),
            wait=bool(data.get("wait", True)),
            ignore_codes=data.get("ignore_codes", []),
        )

    def execute(self, context: "InstallContext") -> StepResult:
        artifacts: list[Artifact] = []
        try:
            exe = context.expand(self.path)
            args = [context.expand(a) for a in self.args]

            context.log(
                f"   ▶ Запуск {exe}",
                f"   ▶ Running {exe}",
            )

            cmd = [exe, *args]
            if self.wait:
                proc = subprocess.run(
                    cmd, creationflags=CREATE_NO_WINDOW
                )
                if proc.returncode != 0 and proc.returncode not in self.ignore_codes:
                    return StepResult(
                        False, artifacts,
                        f"run_exe: '{exe}' exited with code {proc.returncode}",
                    )
            else:
                subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)

            artifacts.append(Artifact(
                type=ARTIFACT_EXE_INSTALL,
                path=exe,
                extra={"args": args},
            ))
            return StepResult(True, artifacts)
        except FileNotFoundError as exc:
            return StepResult(False, artifacts, f"run_exe: file not found: {exc}")
        except Exception as exc:  # noqa: BLE001
            return StepResult(False, artifacts, f"run_exe failed: {exc}")
