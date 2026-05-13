# -*- coding: utf-8 -*-
"""
core.installer
Декларативное ядро установки/проверки/удаления плагинов.

Публичный API:
    InstallContext      — контекст установки (пути, опции, версия AE)
    PluginPipeline      — главный оркестратор: download → extract → install → verify
    InstalledManifest   — запись/чтение/удаление манифестов в installed/
    DetectionCache      — in-memory кэш проверок установлен ли плагин
    custom_plugin_to_manifest — конвертер custom_files → install_steps + detect

[AKSIOM-FIX] Добавлены экспорты ARTIFACT_REG_KEY, SOURCE_MANAGED, SOURCE_LEGACY —
для тестов и плагинов, которые захотят явно регистрировать reg_key артефакты
или различать managed/legacy установки на уровне внешнего кода.
"""

from core.installer.context import InstallContext
from core.installer.manifest import (
    InstalledManifest,
    ARTIFACT_FILE,
    ARTIFACT_DIR,
    ARTIFACT_REG_VALUE,
    ARTIFACT_REG_KEY,
    ARTIFACT_EXE_INSTALL,
    SOURCE_MANAGED,
    SOURCE_LEGACY,
)
from core.installer.cache import DetectionCache
from core.installer.detector import Detector
from core.installer.engine import PluginInstaller
from core.installer.pipeline import PluginPipeline
from core.installer.custom_converter import custom_plugin_to_manifest

__all__ = [
    "InstallContext",
    "PluginPipeline",
    "PluginInstaller",
    "InstalledManifest",
    "DetectionCache",
    "Detector",
    "custom_plugin_to_manifest",
    "ARTIFACT_FILE",
    "ARTIFACT_DIR",
    "ARTIFACT_REG_VALUE",
    "ARTIFACT_REG_KEY",
    "ARTIFACT_EXE_INSTALL",
    "SOURCE_MANAGED",
    "SOURCE_LEGACY",
]
