# -*- coding: utf-8 -*-
"""copy_file.py — копирование одного файла."""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING

from core.installer.manifest import ARTIFACT_FILE, Artifact
from core.installer.steps.base import InstallStep, StepResult

if TYPE_CHECKING:
    from core.installer.context import InstallContext


class CopyFileStep(InstallStep):
    """
    JSON:
        {"type": "copy_file", "source": "{SRC_DIR}/X.aex", "target": "{COMMON_PLUGINS}/X.aex"}

    target может быть как файлом, так и директорией. Если target оканчивается
    на разделитель пути или указывает на существующую директорию — файл
    копируется внутрь, имя берётся из source.
    """

    def __init__(self, source: str, target: str) -> None:
        self.source = source
        self.target = target

    @classmethod
    def from_dict(cls, data: dict) -> "CopyFileStep":
        return cls(source=data["source"], target=data["target"])

    def execute(self, context: "InstallContext") -> StepResult:
        artifacts: list[Artifact] = []
        try:
            src = context.expand(self.source)
            dst = context.expand(self.target)
            if not os.path.exists(src):
                return StepResult(False, artifacts, f"copy_file: source not found: {src}")

            # Определяем итоговый путь
            if dst.endswith(("/", "\\")) or os.path.isdir(dst):
                dst_dir = dst
                final_path = os.path.join(dst_dir, os.path.basename(src))
            else:
                dst_dir = os.path.dirname(dst)
                final_path = dst

            # Создаём директорию, отмечая её как артефакт ТОЛЬКО если её ещё не было
            dir_was_missing = not os.path.exists(dst_dir) if dst_dir else False
            if dst_dir:
                os.makedirs(dst_dir, exist_ok=True)
            if dir_was_missing and dst_dir:
                artifacts.append(Artifact(type="dir", path=dst_dir))

            shutil.copy2(src, final_path)
            artifacts.append(Artifact(type=ARTIFACT_FILE, path=final_path))

            context.log(
                f"   ✓ Скопирован файл → {final_path}",
                f"   ✓ Copied file → {final_path}",
            )
            return StepResult(True, artifacts)
        except Exception as exc:  # noqa: BLE001
            return StepResult(False, artifacts, f"copy_file failed: {exc}")
