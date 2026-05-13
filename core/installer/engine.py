# -*- coding: utf-8 -*-
"""
engine.py
PluginInstaller — оркестратор: парсит install_steps, выполняет в транзакции,
при успехе записывает манифест.

[AKSIOM-FIX #1] Перед циклом выставляет context.transaction = tx, чтобы шаги
вроде CopyDirStep могли регистрировать pending backups через транзакцию.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from core.installer.manifest import (
    InstalledManifest,
    SOURCE_LEGACY,
    SOURCE_MANAGED,
)
from core.installer.steps import build_steps
from core.installer.transaction import InstallTransaction

if TYPE_CHECKING:
    from core.installer.context import InstallContext


class PluginInstaller:
    """
    Точка входа на установку одного плагина (без скачивания/распаковки —
    это делает PluginPipeline, см. pipeline.py).
    """

    def __init__(
        self,
        installed_dir: str,
        legacy_install: Callable[[dict, "InstallContext"], bool] | None = None,
    ) -> None:
        self.installed_dir = installed_dir
        self.legacy_install = legacy_install

    def install(self, plugin: dict, context: "InstallContext") -> bool:
        """
        Возвращает True при успехе. Манифест записывается только при успехе.
        При сбое любого шага транзакция откатывает уже созданные артефакты.
        """
        steps_data = plugin.get("install_steps")

        # Fallback на legacy для плагинов без install_steps
        if not steps_data:
            if self.legacy_install is None:
                context.log(
                    f"[!] У плагина {context.plugin_name} нет install_steps "
                    f"и нет legacy_install — пропуск.",
                    f"[!] Plugin {context.plugin_name} has no install_steps "
                    f"and no legacy_install — skipping.",
                )
                return False
            try:
                ok = bool(self.legacy_install(plugin, context))
            except Exception as exc:  # noqa: BLE001
                context.log(
                    f"❌ Ошибка legacy-установки {context.plugin_name}: {exc}",
                    f"❌ Legacy install error for {context.plugin_name}: {exc}",
                )
                return False
            if ok:
                InstalledManifest.write(
                    self.installed_dir,
                    context.plugin_name,
                    context.ae_version,
                    plugin,
                    artifacts=[],
                    source=SOURCE_LEGACY,
                )
            return ok

        # Декларативный путь
        try:
            steps = build_steps(steps_data)
        except ValueError as exc:
            context.log(
                f"❌ Ошибка парсинга install_steps {context.plugin_name}: {exc}",
                f"❌ Error parsing install_steps for {context.plugin_name}: {exc}",
            )
            return False

        with InstallTransaction(context) as tx:
            # [AKSIOM-FIX #1] Прокидываем транзакцию в context для шагов
            context.transaction = tx
            try:
                for i, step in enumerate(steps, 1):
                    context.log(
                        f"   ── шаг {i}/{len(steps)}: {type(step).__name__}",
                        f"   ── step {i}/{len(steps)}: {type(step).__name__}",
                    )
                    result = step.execute(context)
                    tx.add_artifacts(result.artifacts)
                    if not result.success:
                        context.log(
                            f"❌ Шаг провален: {result.error}",
                            f"❌ Step failed: {result.error}",
                        )
                        return False
                tx.commit()
            finally:
                # [AKSIOM-FIX #1] Снимаем ссылку, чтобы не утекала
                context.transaction = None

        InstalledManifest.write(
            self.installed_dir,
            context.plugin_name,
            context.ae_version,
            plugin,
            artifacts=tx.committed_artifacts,
            source=SOURCE_MANAGED,
        )
        context.log(
            f"✅ {context.plugin_name} установлен успешно.",
            f"✅ {context.plugin_name} installed successfully.",
        )
        return True
