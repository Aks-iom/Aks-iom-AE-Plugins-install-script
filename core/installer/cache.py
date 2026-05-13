# -*- coding: utf-8 -*-
"""
cache.py
DetectionCache — in-memory кэш результатов is_plugin_installed.

Ключ — (plugin_name, ae_version). TTL по умолчанию 60 сек.
Инвалидация — после установки/удаления конкретного плагина.
"""

from __future__ import annotations

import threading
import time


class DetectionCache:
    def __init__(self, ttl: int = 60) -> None:
        self._cache: dict[tuple[str, str], tuple[bool, float]] = {}
        self._ttl = ttl
        self._lock = threading.Lock()

    def get(self, plugin: str, ae_version: str) -> bool | None:
        with self._lock:
            entry = self._cache.get((plugin, ae_version))
            if entry is None:
                return None
            value, ts = entry
            if (time.time() - ts) > self._ttl:
                # просрочено
                self._cache.pop((plugin, ae_version), None)
                return None
            return value

    def set(self, plugin: str, ae_version: str, result: bool) -> None:
        with self._lock:
            self._cache[(plugin, ae_version)] = (result, time.time())

    def invalidate(
        self,
        plugin: str | None = None,
        ae_version: str | None = None,
    ) -> None:
        """
        Инвалидация:
          - без аргументов — очистка всего кэша
          - только plugin — все версии этого плагина
          - только ae_version — все плагины для этой версии
          - оба — конкретная пара
        """
        with self._lock:
            if plugin is None and ae_version is None:
                self._cache.clear()
                return
            keys_to_remove = [
                k for k in self._cache
                if (plugin is None or k[0] == plugin)
                and (ae_version is None or k[1] == ae_version)
            ]
            for k in keys_to_remove:
                self._cache.pop(k, None)
