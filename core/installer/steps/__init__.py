# -*- coding: utf-8 -*-
"""
core.installer.steps
Фабрика build_steps() и публичный реестр шагов.

Каждый JSON-объект install_steps имеет ключ "type". Этот модуль маппит
строку "type" → соответствующий класс шага и возвращает список объектов
InstallStep, готовых к выполнению PluginInstaller'ом.
"""

from __future__ import annotations

from core.installer.steps.base import InstallStep, StepResult
from core.installer.steps.copy_dir import CopyDirStep
from core.installer.steps.copy_file import CopyFileStep
from core.installer.steps.extract_zip import ExtractZipStep
from core.installer.steps.if_step import IfStep
from core.installer.steps.kill_process import KillProcessStep
from core.installer.steps.registry import (
    EnableCepDebugStep,
    ImportRegStep,
    SetRegValueStep,
)
from core.installer.steps.run_exe import RunExeStep


# ---------------------------------------------------------------------------
# Реестр шагов: "type" из JSON → класс
# ---------------------------------------------------------------------------
_STEP_REGISTRY: dict[str, type[InstallStep]] = {
    "copy_file":        CopyFileStep,
    "copy_dir":         CopyDirStep,
    "extract_zip":      ExtractZipStep,
    "if":               IfStep,
    "kill_process":     KillProcessStep,
    "import_reg":       ImportRegStep,
    "set_reg_value":    SetRegValueStep,
    "enable_cep_debug": EnableCepDebugStep,
    "run_exe":          RunExeStep,
}


def build_steps(steps_data: list[dict] | None) -> list[InstallStep]:
    """
    Преобразует список JSON-описаний шагов в список объектов InstallStep.

    Бросает ValueError, если шаг неизвестного типа или невалиден.
    Пустой/None список → пустой результат (не ошибка).
    """
    if not steps_data:
        return []

    if not isinstance(steps_data, list):
        raise ValueError(
            f"install_steps must be a list, got {type(steps_data).__name__}"
        )

    result: list[InstallStep] = []
    for i, raw in enumerate(steps_data, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"step #{i}: must be a dict, got {type(raw).__name__}")

        step_type = raw.get("type")
        if not step_type:
            raise ValueError(f"step #{i}: missing 'type'")

        cls = _STEP_REGISTRY.get(step_type)
        if cls is None:
            raise ValueError(f"step #{i}: unknown step type '{step_type}'")

        try:
            result.append(cls.from_dict(raw))
        except KeyError as exc:
            raise ValueError(
                f"step #{i} ({step_type}): missing required field {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                f"step #{i} ({step_type}): {exc}"
            ) from exc

    return result


__all__ = [
    "InstallStep",
    "StepResult",
    "build_steps",
    "CopyFileStep",
    "CopyDirStep",
    "ExtractZipStep",
    "IfStep",
    "KillProcessStep",
    "ImportRegStep",
    "SetRegValueStep",
    "EnableCepDebugStep",
    "RunExeStep",
]
