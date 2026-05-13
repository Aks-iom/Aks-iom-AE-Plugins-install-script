# -*- coding: utf-8 -*-
"""copy_dir.py — копирование директории.

[AKSIOM-FIX #1] Replace-режим теперь регистрирует бэкап в транзакции.
Бэкап удаляется ТОЛЬКО при общем commit() транзакции; при rollback —
автоматически восстанавливается. Это защищает от потери данных, если
установка падает уже после успеха copy_dir.
"""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING

from core.installer.manifest import ARTIFACT_DIR, ARTIFACT_FILE, Artifact
from core.installer.steps.base import InstallStep, StepResult

if TYPE_CHECKING:
    from core.installer.context import InstallContext


class CopyDirStep(InstallStep):
    """
    JSON:
        {"type": "copy_dir", "source": "{SRC_DIR}/lib", "target": "{PF}/X/lib", "mode": "merge"}

    mode:
      - "merge"   (по умолчанию) — dirs_exist_ok=True, добавляет файлы
      - "replace" — если target существует, переименовывается в .aksiom_bak;
                    бэкап удаляется ТОЛЬКО при общем commit() транзакции,
                    при rollback всей транзакции — восстанавливается обратно.
    """

    def __init__(self, source: str, target: str, mode: str = "merge") -> None:
        self.source = source
        self.target = target
        self.mode = mode if mode in ("merge", "replace") else "merge"

    @classmethod
    def from_dict(cls, data: dict) -> "CopyDirStep":
        return cls(
            source=data["source"],
            target=data["target"],
            mode=data.get("mode", "merge"),
        )

    def execute(self, context: "InstallContext") -> StepResult:
        artifacts: list[Artifact] = []
        backup_dir: str | None = None
        try:
            src = context.expand(self.source)
            dst = context.expand(self.target)
            if not os.path.exists(src):
                return StepResult(False, artifacts, f"copy_dir: source not found: {src}")
            if not os.path.isdir(src):
                return StepResult(False, artifacts, f"copy_dir: source is not a dir: {src}")

            target_existed = os.path.exists(dst)

            if self.mode == "replace" and target_existed:
                backup_dir = dst + ".aksiom_bak"
                if os.path.exists(backup_dir):
                    shutil.rmtree(backup_dir, ignore_errors=True)
                try:
                    os.rename(dst, backup_dir)
                except OSError as exc:
                    return StepResult(
                        False, artifacts,
                        f"copy_dir(replace): cannot backup target: {exc}",
                    )
                target_existed = False

                # [AKSIOM-FIX #1] Регистрируем бэкап в транзакции, если она доступна.
                # Если транзакции нет (запуск из тестов или legacy-кода) — поведение
                # как раньше: успех = удаляем бэкап в конце execute().
                tx = getattr(context, "transaction", None)
                if tx is not None and hasattr(tx, "register_backup"):
                    tx.register_backup(dst, backup_dir)
                    # бэкап теперь под управлением транзакции, не удаляем здесь
                    backup_dir = None

            if not target_existed:
                shutil.copytree(src, dst, dirs_exist_ok=True)
                artifacts.append(Artifact(type=ARTIFACT_DIR, path=dst))
            else:
                # Merge-режим
                for root, dirs, files in os.walk(src):
                    rel = os.path.relpath(root, src)
                    dst_root = os.path.normpath(os.path.join(dst, rel))
                    if not os.path.exists(dst_root):
                        os.makedirs(dst_root, exist_ok=True)
                        artifacts.append(Artifact(type=ARTIFACT_DIR, path=dst_root))
                    for f in files:
                        src_f = os.path.join(root, f)
                        dst_f = os.path.join(dst_root, f)
                        if not os.path.exists(dst_f):
                            shutil.copy2(src_f, dst_f)
                            artifacts.append(Artifact(type=ARTIFACT_FILE, path=dst_f))

            # [AKSIOM-FIX #1] Если бэкап остался под нашим управлением (нет транзакции) —
            # удаляем его, как раньше. С транзакцией он будет удалён в commit().
            if backup_dir is not None and os.path.exists(backup_dir):
                shutil.rmtree(backup_dir, ignore_errors=True)

            context.log(
                f"   ✓ Скопирована папка → {dst}",
                f"   ✓ Copied directory → {dst}",
            )
            return StepResult(True, artifacts)
        except Exception as exc:  # noqa: BLE001
            # При сбое — восстанавливаем бэкап, если он ещё под нашим контролем
            if backup_dir is not None and os.path.exists(backup_dir):
                try:
                    if os.path.exists(dst):
                        shutil.rmtree(dst, ignore_errors=True)
                    os.rename(backup_dir, dst)
                    context.log(
                        f"   ↶ Восстановлен предыдущий target из бэкапа: {dst}",
                        f"   ↶ Restored previous target from backup: {dst}",
                    )
                except OSError:
                    pass
            return StepResult(False, artifacts, f"copy_dir failed: {exc}")
