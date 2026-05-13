# -*- coding: utf-8 -*-
"""extract_zip.py — распаковка zip-архива."""

from __future__ import annotations

import os
import zipfile
from typing import TYPE_CHECKING

from core.installer.manifest import ARTIFACT_DIR, ARTIFACT_FILE, Artifact
from core.installer.steps.base import InstallStep, StepResult

if TYPE_CHECKING:
    from core.installer.context import InstallContext


class ExtractZipStep(InstallStep):
    """
    JSON:
        {"type": "extract_zip", "source": "{SRC_DIR}/x.zip", "target": "{PLUGINS_DIR}/X"}

    Артефакты:
      - Целевая папка (если её не было)
      - Каждый извлечённый файл — ARTIFACT_FILE (для гранулярного отката)
    """

    def __init__(self, source: str, target: str) -> None:
        self.source = source
        self.target = target

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractZipStep":
        return cls(source=data["source"], target=data["target"])

    def execute(self, context: "InstallContext") -> StepResult:
        artifacts: list[Artifact] = []
        try:
            src = context.expand(self.source)
            dst = context.expand(self.target)

            if not os.path.exists(src):
                return StepResult(False, artifacts, f"extract_zip: source not found: {src}")
            if not zipfile.is_zipfile(src):
                return StepResult(False, artifacts, f"extract_zip: not a zip: {src}")

            target_existed = os.path.exists(dst)
            os.makedirs(dst, exist_ok=True)
            if not target_existed:
                artifacts.append(Artifact(type=ARTIFACT_DIR, path=dst))

            dst_abs = os.path.realpath(dst)
            with zipfile.ZipFile(src, "r") as z:
                # SAFETY: Zip Slip — проверяем, что все члены архива остаются
                # внутри dst после нормализации (на случай "../../etc/passwd")
                for member in z.namelist():
                    target_path = os.path.realpath(
                        os.path.join(dst, member.replace("/", os.sep))
                    )
                    if not (target_path == dst_abs
                            or target_path.startswith(dst_abs + os.sep)):
                        return StepResult(
                            False, artifacts,
                            f"extract_zip: unsafe path in archive: {member}",
                        )

                for member in z.namelist():
                    # extract возвращает реальный путь распакованного файла
                    extracted_path = z.extract(member, dst)
                    if member.endswith(("/", "\\")):
                        if not target_existed:  # уже учли как часть target_dir
                            continue
                        if not os.path.exists(extracted_path):
                            continue
                        artifacts.append(Artifact(type=ARTIFACT_DIR, path=extracted_path))
                    else:
                        artifacts.append(Artifact(type=ARTIFACT_FILE, path=extracted_path))

            context.log(
                f"   ✓ Распакован архив → {dst}",
                f"   ✓ Extracted zip → {dst}",
            )
            return StepResult(True, artifacts)
        except Exception as exc:  # noqa: BLE001
            return StepResult(False, artifacts, f"extract_zip failed: {exc}")
