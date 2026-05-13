# -*- coding: utf-8 -*-
"""
base.py
InstallStep (ABC) и StepResult.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.installer.manifest import Artifact

if TYPE_CHECKING:
    from core.installer.context import InstallContext


@dataclass
class StepResult:
    success: bool
    artifacts: list[Artifact] = field(default_factory=list)
    error: str | None = None


class InstallStep(ABC):
    """
    Базовый класс шага установки.

    Контракт: execute() обязан вернуть StepResult, заполнив:
      - success: True/False
      - artifacts: список ВСЕХ созданных на диске/в реестре объектов;
        при ошибке — артефакты, успевшие создаться до ошибки (для отката)
      - error: текст ошибки, если success=False
    """

    @abstractmethod
    def execute(self, context: "InstallContext") -> StepResult: ...

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict) -> "InstallStep": ...
