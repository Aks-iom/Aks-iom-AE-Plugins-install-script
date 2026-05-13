# -*- coding: utf-8 -*-
"""
pipeline.py
PluginPipeline — самый верхний уровень:

  1. ensure_downloaded(plugin)        — gdown + md5
  2. ensure_extracted(plugin)         — распаковка zip в src_dir
  3. PluginInstaller.install(...)     — выполнение install_steps
  4. (запись манифеста — внутри install)
  5. verify_installation(...)         — перепроверка через detect

Делегаты download/extract принимаются параметрами, чтобы не дублировать
логику gdown — она уже отлажена в InstallerLogicMixin.

[AKSIOM-FIX #25] is_plugin_installed: lazy-чтение манифеста (читаем один раз
за вызов вместо нескольких через is_present).
"""

from __future__ import annotations

import os
from typing import Callable

from core.installer.cache import DetectionCache
from core.installer.context import InstallContext, build_default_paths
from core.installer.custom_converter import custom_plugin_to_manifest
from core.installer.detector import Detector
from core.installer.engine import PluginInstaller
from core.installer.manifest import (
    Artifact,
    InstalledManifest,
    SOURCE_LEGACY,
    SOURCE_MANAGED,
    remove_artifact,
)


# ---------------------------------------------------------------------------
# Whitelist путей, в которых разрешено удалять при legacy-uninstall
# ---------------------------------------------------------------------------
_WHITELIST_TEMPLATES = [
    "{PF}\\BorisFX",
    "{PF}\\Maxon",
    "{PF}\\GenArts",
    "{PF}\\Red Giant",
    "{PF}\\Adobe\\Common\\Plug-ins",
    "{PF86}\\Common Files\\Adobe\\CEP\\extensions",
    "{PROGRAMDATA}\\GenArts",
    "{PROGRAMDATA}\\VideoCopilot",
    "{PROGRAMDATA}\\Maxon",
    "{PROGRAMDATA}\\Red Giant",
    "{PLUGINS_DIR}",
    "{SCRIPTS_DIR}",
    "{COMMON_PLUGINS}",
    "{CEP_EXTENSIONS}",
    "{USER_DOCS}\\VideoCopilot",
]


def _is_path_whitelisted(path: str, context: InstallContext) -> bool:
    """Проверяет, лежит ли path внутри одной из whitelist-директорий."""
    if not path:
        return False
    norm = os.path.normcase(os.path.normpath(path))
    for tpl in _WHITELIST_TEMPLATES:
        wl = os.path.normcase(os.path.normpath(context.expand(tpl)))
        if wl and (norm == wl or norm.startswith(wl + os.sep)):
            return True
    return False


class PluginPipeline:
    """См. модульный docstring."""

    def __init__(
        self,
        cache_dir: str,
        installed_dir: str,
        ae_drive: str = "",
        custom_install_path: str = "",
        options: dict | None = None,
        logger: Callable[[str, str], None] | None = None,
        legacy_install: Callable[[dict, InstallContext], bool] | None = None,
        legacy_uninstall: Callable[[str, str], bool] | None = None,
        download_fn: Callable[[str, str, str, int, int], bool] | None = None,
        extract_fn: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.installed_dir = installed_dir
        self.ae_drive = ae_drive
        self.custom_install_path = custom_install_path
        self.options = options or {}
        self.logger = logger or (lambda _ru, _en: None)
        self.legacy_install = legacy_install
        self.legacy_uninstall = legacy_uninstall
        self.download_fn = download_fn
        self.extract_fn = extract_fn

        self.cache = DetectionCache(ttl=60)
        self.engine = PluginInstaller(
            installed_dir=installed_dir,
            legacy_install=legacy_install,
        )

        os.makedirs(self.installed_dir, exist_ok=True)

    # ------------------------------------------------------------------
    def update_settings(
        self,
        ae_drive: str | None = None,
        custom_install_path: str | None = None,
        options: dict | None = None,
    ) -> None:
        if ae_drive is not None:
            self.ae_drive = ae_drive
        if custom_install_path is not None:
            self.custom_install_path = custom_install_path
        if options is not None:
            self.options = options
        self.cache.invalidate()

    # ------------------------------------------------------------------
    def make_context(
        self,
        plugin: dict,
        ae_version: str,
        src_dir: str,
        custom_path: str | None = None,
    ) -> InstallContext:
        paths = build_default_paths(
            ae_version=ae_version,
            ae_drive=self.ae_drive,
            custom_install_path=self.custom_install_path,
        )
        return InstallContext(
            plugin_name=plugin.get("name", ""),
            ae_version=ae_version,
            src_dir=src_dir,
            paths=paths,
            custom_path=custom_path,
            options=dict(self.options),
            logger=self.logger,
        )

    # ==================================================================
    def ensure_downloaded(self, plugin: dict, idx: int, total: int) -> bool:
        if self.download_fn is None:
            self.logger(
                "[!] download_fn не сконфигурирован — пропуск загрузки.",
                "[!] download_fn not configured — skipping download.",
            )
            return False
        return bool(self.download_fn(
            plugin.get("gdrive_id", ""),
            self._archive_path(plugin),
            plugin.get("name", "Plugin"),
            idx, total,
        ))

    def _archive_path(self, plugin: dict) -> str:
        name = plugin.get("name", "Plugin")
        return os.path.join(self.cache_dir, f"{name}.zip")

    # ==================================================================
    def ensure_extracted(self, plugin: dict) -> str | None:
        if plugin.get("custom_files"):
            return self.cache_dir

        if self.extract_fn is None:
            return None

        zip_path = self._archive_path(plugin)
        if not os.path.exists(zip_path):
            bat_path = plugin.get("bat_path", "")
            if bat_path and bat_path != "CUSTOM":
                src_dir = os.path.dirname(os.path.join(self.cache_dir, bat_path))
                if os.path.isdir(src_dir):
                    return src_dir
            return None

        target = os.path.join(self.cache_dir, plugin.get("name", "Plugin"))
        if self.extract_fn(zip_path, target):
            return target
        return None

    # ==================================================================
    def install(
        self,
        plugin: dict,
        ae_version: str,
        src_dir: str,
        custom_path: str | None = None,
    ) -> bool:
        if plugin.get("custom_files") and not plugin.get("install_steps"):
            plugin = custom_plugin_to_manifest(plugin)

        ctx = self.make_context(plugin, ae_version, src_dir, custom_path)
        ok = self.engine.install(plugin, ctx)
        self.cache.invalidate(plugin.get("name", ""), ae_version)
        return ok

    # ==================================================================
    def verify_installation(self, plugin: dict, ae_version: str) -> bool:
        return self.is_plugin_installed(plugin, ae_version, use_cache=False)

    # ==================================================================
    def is_plugin_installed(
        self,
        plugin: dict,
        ae_version: str,
        *,
        use_cache: bool = True,
        legacy_check: Callable[[str, str], bool] | None = None,
    ) -> bool:
        """
        Алгоритм:
          1. Манифест installed/<plugin>__<version>.json существует и все
             артефакты на месте → True
          2. detect-блок в plugin → выполнить условия
          3. legacy_check (если передан) → fallback на keyword-поиск

        Все True-ответы кэшируются на 60 сек.
        """
        plugin_name = plugin.get("name", "")
        if not plugin_name or ae_version == "None":
            return False

        if use_cache:
            cached = self.cache.get(plugin_name, ae_version)
            if cached is not None:
                return cached

        # 1. Манифест
        manifest = InstalledManifest.read(self.installed_dir, plugin_name, ae_version)
        if manifest is not None:
            if manifest.get("source") == SOURCE_MANAGED and manifest.get("artifacts"):
                if InstalledManifest.artifacts_present(manifest):
                    self.cache.set(plugin_name, ae_version, True)
                    return True
                # манифест устарел — удаляем
                InstalledManifest.delete(self.installed_dir, plugin_name, ae_version)
            elif manifest.get("source") == SOURCE_LEGACY:
                # legacy-манифест без артефактов — продолжаем проверки ниже
                pass

        # 2. detect-блок
        if plugin.get("detect"):
            ctx = self.make_context(plugin, ae_version, src_dir="")
            if Detector.evaluate(plugin["detect"], ctx):
                InstalledManifest.write(
                    self.installed_dir, plugin_name, ae_version,
                    plugin, artifacts=[], source=SOURCE_LEGACY,
                )
                self.cache.set(plugin_name, ae_version, True)
                return True

        # 3. legacy fallback
        if legacy_check is not None:
            try:
                if bool(legacy_check(plugin_name, ae_version)):
                    InstalledManifest.write(
                        self.installed_dir, plugin_name, ae_version,
                        plugin, artifacts=[], source=SOURCE_LEGACY,
                    )
                    self.cache.set(plugin_name, ae_version, True)
                    return True
            except Exception as exc:  # noqa: BLE001
                self.logger(
                    f"[!] legacy_check({plugin_name}): {exc}",
                    f"[!] legacy_check({plugin_name}): {exc}",
                )

        self.cache.set(plugin_name, ae_version, False)
        return False

    # ==================================================================
    def uninstall(
        self,
        plugin: dict,
        ae_version: str,
        legacy_uninstall: Callable[[str, str], bool] | None = None,
    ) -> bool:
        plugin_name = plugin.get("name", "")

        if plugin.get("uninstall_method") == "control_panel":
            return False

        manifest = InstalledManifest.read(self.installed_dir, plugin_name, ae_version)

        if manifest and manifest.get("source") == SOURCE_MANAGED and manifest.get("artifacts"):
            artifacts = [Artifact.from_dict(a) for a in manifest["artifacts"]]
            self.logger(
                f"[*] Удаление {plugin_name} по манифесту "
                f"({len(artifacts)} артефактов)...",
                f"[*] Uninstalling {plugin_name} by manifest "
                f"({len(artifacts)} artifacts)...",
            )
            deleted_any = False
            for art in reversed(artifacts):
                if remove_artifact(art, ignore_errors=True):
                    deleted_any = True
            InstalledManifest.delete(self.installed_dir, plugin_name, ae_version)
            self.cache.invalidate(plugin_name, ae_version)
            return deleted_any

        legacy = legacy_uninstall or self.legacy_uninstall
        if legacy is None:
            self.logger(
                f"[!] Нет манифеста и нет legacy_uninstall для {plugin_name}.",
                f"[!] No manifest and no legacy_uninstall for {plugin_name}.",
            )
            return False

        if manifest:
            InstalledManifest.delete(self.installed_dir, plugin_name, ae_version)

        try:
            ok = bool(legacy(plugin_name, ae_version))
        except Exception as exc:  # noqa: BLE001
            self.logger(
                f"❌ legacy_uninstall({plugin_name}): {exc}",
                f"❌ legacy_uninstall({plugin_name}): {exc}",
            )
            ok = False

        self.cache.invalidate(plugin_name, ae_version)
        return ok

    # ==================================================================
    def is_path_safe_to_remove(self, path: str, ae_version: str) -> bool:
        ctx = InstallContext(
            plugin_name="",
            ae_version=ae_version,
            src_dir="",
            paths=build_default_paths(
                ae_version=ae_version,
                ae_drive=self.ae_drive,
                custom_install_path=self.custom_install_path,
            ),
            options=dict(self.options),
        )
        return _is_path_whitelisted(path, ctx)
