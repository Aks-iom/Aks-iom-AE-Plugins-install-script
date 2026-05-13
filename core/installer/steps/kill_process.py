# -*- coding: utf-8 -*-
"""kill_process.py — taskkill процесса по имени."""

from __future__ import annotations

import subprocess
import sys
import time
from typing import TYPE_CHECKING

from core.installer.steps.base import InstallStep, StepResult

if TYPE_CHECKING:
    from core.installer.context import InstallContext


CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class KillProcessStep(InstallStep):
    """
    JSON:
        {"type": "kill_process", "name": "Maxon App.exe", "delay": 4}

    delay (сек) — пауза ДО taskkill (некоторые инсталлеры запускают свои
    процессы не сразу, нужно дать им время).

    Артефактов не создаёт. Если процесс не найден — это не ошибка.
    """

    def __init__(self, name: str, delay: float = 0) -> None:
        self.name = name
        self.delay = float(delay or 0)

    @classmethod
    def from_dict(cls, data: dict) -> "KillProcessStep":
        return cls(name=data["name"], delay=data.get("delay", 0))

    def execute(self, context: "InstallContext") -> StepResult:
        try:
            if self.delay > 0:
                time.sleep(self.delay)

            if sys.platform != "win32":
                # На не-Windows тихо пропускаем — нет смысла падать
                return StepResult(True, [])

            subprocess.run(
                ["taskkill", "/F", "/IM", self.name, "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
            context.log(
                f"   ✓ Процесс остановлен: {self.name}",
                f"   ✓ Process killed: {self.name}",
            )
            return StepResult(True, [])
        except Exception as exc:  # noqa: BLE001
            # taskkill редко падает, но даже если упал — не считаем шаг провалом
            context.log(
                f"   ! taskkill {self.name}: {exc}",
                f"   ! taskkill {self.name}: {exc}",
            )
            return StepResult(True, [])
