# -*- coding: utf-8 -*-
"""if_step.py — шаг-условие с ветвлением then/else."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from core.installer.manifest import Artifact
from core.installer.steps.base import InstallStep, StepResult

if TYPE_CHECKING:
    from core.installer.context import InstallContext


# Простой парсер условий: "options.X", "!options.X", "options.X == 'value'"
_EQ_RE = re.compile(r"^\s*(\!?)\s*([\w\.]+)\s*(?:==\s*(['\"]?)([^'\"]+)\3)?\s*$")


def _eval_condition(cond: str, context: "InstallContext") -> bool:
    """
    Поддерживает:
      "options.old_rsmb"               — bool(value)
      "!options.old_rsmb"              — not bool(value)
      "options.foo == 'bar'"           — равенство строк
      "options.foo == 1"               — равенство значений (через str())
    """
    m = _EQ_RE.match(cond)
    if not m:
        # Нераспознанное условие — считаем False, не падаем
        context.log(
            f"   ! if: не понял условие '{cond}', результат = False",
            f"   ! if: cannot parse '{cond}', returning False",
        )
        return False
    negate = m.group(1) == "!"
    dotted = m.group(2)
    expected = m.group(4)

    # достаём значение
    parts = dotted.split(".")
    if parts[0] == "options":
        parts = parts[1:]
    cur: object = context.options
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            cur = None
            break

    if expected is None:
        result = bool(cur)
    else:
        result = str(cur) == expected

    return (not result) if negate else result


class IfStep(InstallStep):
    """
    JSON:
        {
          "type": "if",
          "condition": "options.old_rsmb",
          "then": [ {...step1}, {...step2} ],
          "else": [ {...stepA} ]
        }

    Условия (минимальный язык, не eval):
      - "options.<key>"                   — truthy
      - "!options.<key>"                  — falsy
      - "options.<key> == 'value'"        — равенство строк

    Артефакты вложенных шагов «прозрачно» поднимаются наверх — InstallTransaction
    их получит и сможет откатить.
    """

    def __init__(
        self,
        condition: str,
        then_steps: list[InstallStep],
        else_steps: list[InstallStep] | None = None,
    ) -> None:
        self.condition = condition
        self.then_steps = then_steps
        self.else_steps = else_steps or []

    @classmethod
    def from_dict(cls, data: dict) -> "IfStep":
        # Локальный импорт — избегаем циклического (steps/__init__ → if_step → __init__)
        from core.installer.steps import build_steps
        return cls(
            condition=data["condition"],
            then_steps=build_steps(data.get("then", [])),
            else_steps=build_steps(data.get("else", [])),
        )

    def execute(self, context: "InstallContext") -> StepResult:
        artifacts: list[Artifact] = []
        try:
            cond_value = _eval_condition(self.condition, context)
            branch = self.then_steps if cond_value else self.else_steps

            context.log(
                f"   ⟶ if({self.condition}) = {cond_value}, "
                f"выполняю {len(branch)} шагов",
                f"   ⟶ if({self.condition}) = {cond_value}, "
                f"running {len(branch)} steps",
            )

            for sub in branch:
                result = sub.execute(context)
                # Артефакты собираем независимо от успеха —
                # это нужно для отката через transaction
                artifacts.extend(result.artifacts)
                if not result.success:
                    return StepResult(False, artifacts, f"if-branch step failed: {result.error}")

            return StepResult(True, artifacts)
        except Exception as exc:  # noqa: BLE001
            return StepResult(False, artifacts, f"if step failed: {exc}")
