# -*- coding: utf-8 -*-
"""
transaction.py
InstallTransaction — context manager, накапливающий артефакты и откатывающий
их, если установка завершилась ошибкой / не была явно зафиксирована commit().

[AKSIOM-FIX #1] Добавлен механизм pending_backups: бэкапы целевых директорий,
созданные шагами вроде copy_dir(replace), удаляются ТОЛЬКО при commit().
При rollback() — бэкапы автоматически восстанавливаются на место артефактов
типа DIR. Это защищает данные пользователя от потери, если установка падает
ПОСЛЕ успеха «replace»-копирования, но ДО общего commit().
"""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING

from core.installer.manifest import (
    ARTIFACT_DIR,
    ARTIFACT_EXE_INSTALL,
    Artifact,
    remove_artifact,
)

if TYPE_CHECKING:
    from core.installer.context import InstallContext


class InstallTransaction:
    """
    Использование:

        with InstallTransaction(context) as tx:
            for step in steps:
                result = step.execute(context)
                if not result.success:
                    return False     # __exit__ откатит всё накопленное
                tx.add_artifacts(result.artifacts)
            tx.commit()              # фиксация — отката не будет

    Шаги, которые делают backup существующих файлов перед перезаписью,
    могут зарегистрировать его через `tx.register_backup(target, backup_path)`.
    Бэкап удаляется при commit(), восстанавливается при rollback().
    """

    def __init__(self, context: "InstallContext") -> None:
        self.context = context
        self.committed_artifacts: list[Artifact] = []
        # [AKSIOM-FIX #1] target_path → backup_path
        self.pending_backups: dict[str, str] = {}
        self._committed = False
        self._rolled_back = False

    def __enter__(self) -> "InstallTransaction":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None or not self._committed:
            self.rollback()
        return False

    def add_artifacts(self, artifacts: list[Artifact]) -> None:
        if artifacts:
            self.committed_artifacts.extend(artifacts)

    def register_backup(self, target_path: str, backup_path: str) -> None:
        """[AKSIOM-FIX #1] Регистрирует бэкап для позднего удаления/восстановления."""
        if target_path and backup_path:
            self.pending_backups[target_path] = backup_path

    def commit(self) -> None:
        self._committed = True
        # [AKSIOM-FIX #1] Удаляем все бэкапы — установка зафиксирована
        for _target, backup in self.pending_backups.items():
            if backup and os.path.exists(backup):
                shutil.rmtree(backup, ignore_errors=True)
        self.pending_backups.clear()

    def rollback(self) -> None:
        if self._rolled_back:
            return
        self._rolled_back = True

        if not self.committed_artifacts and not self.pending_backups:
            return

        self.context.log(
            "[!] Откат: удаление частично установленных файлов...",
            "[!] Rollback: removing partially installed files...",
        )

        warned_about_exe = False
        for art in reversed(self.committed_artifacts):
            if art.type == ARTIFACT_EXE_INSTALL:
                if not warned_about_exe:
                    self.context.log(
                        f"⚠️ '{art.path}' установлен через .exe-инсталлер. "
                        f"Удалите его вручную через «Программы и компоненты», если нужно.",
                        f"⚠️ '{art.path}' was installed via .exe installer. "
                        f"Uninstall manually via 'Programs and Features' if needed.",
                    )
                    warned_about_exe = True
                continue
            try:
                remove_artifact(art, ignore_errors=True)
            except Exception as exc:  # noqa: BLE001
                self.context.log(
                    f"   Не удалось откатить {art.path}: {exc}",
                    f"   Failed to rollback {art.path}: {exc}",
                )

        # [AKSIOM-FIX #1] Восстановление бэкапов
        for target, backup in self.pending_backups.items():
            if not backup or not os.path.exists(backup):
                continue
            try:
                if os.path.exists(target):
                    shutil.rmtree(target, ignore_errors=True)
                os.rename(backup, target)
                self.context.log(
                    f"   ↶ Восстановлен оригинал из бэкапа: {target}",
                    f"   ↶ Restored original from backup: {target}",
                )
            except OSError as exc:
                self.context.log(
                    f"   ! Не удалось восстановить бэкап {backup} → {target}: {exc}",
                    f"   ! Failed to restore backup {backup} → {target}: {exc}",
                )
        self.pending_backups.clear()
