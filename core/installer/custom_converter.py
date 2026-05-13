# -*- coding: utf-8 -*-
"""
custom_converter.py
Конвертирует custom_files (формат custom_configs/*.json) в install_steps + detect.

Это позволяет UI-конфигуратору кастомных плагинов (часть UI) оставаться без
изменений — пользователь по-прежнему задаёт zip/exe/file/reg + target_path,
а ядро на лету превращает это в манифест.
"""

from __future__ import annotations

import os


def custom_plugin_to_manifest(custom_plugin: dict) -> dict:
    """
    Принимает dict из custom_configs/*.json (одну запись из "plugins": [...]).
    Возвращает копию с добавленными install_steps и detect.

    Соглашения о путях:
      Если у custom_files[t_id] нет target_path:
        zip   → распаковка в {PLUGINS_DIR}/<plugin_name>
        file  → копия в {PLUGINS_DIR}
        exe   → запуск (без копии куда-либо)
        reg   → импорт

    Файл лежит в {SRC_DIR}/<filename> (где SRC_DIR в нашем случае — base_dir,
    туда _ensure_downloaded скачивает custom-файлы; pipeline настроит
    src_dir именно так — см. pipeline.py).
    """
    name = custom_plugin.get("name", "")
    custom_files = custom_plugin.get("custom_files", {}) or {}

    install_steps: list[dict] = []
    detect: list[dict] = []

    for t_id, f_info in custom_files.items():
        filename = f_info.get("filename", "")
        target_path = (f_info.get("target_path") or "").strip()
        source_path = "{SRC_DIR}/" + filename if filename else ""

        if t_id == "zip":
            extract_target = target_path or os.path.join(
                "{PLUGINS_DIR}", name
            ).replace("\\", "/")
            install_steps.append({
                "type": "extract_zip",
                "source": source_path,
                "target": extract_target,
            })
            detect.append({
                "type": "dir_exists",
                "path": extract_target,
                "non_empty": True,
            })

        elif t_id == "exe":
            install_steps.append({
                "type": "run_exe",
                "path": source_path,
                "args": [],
                "wait": True,
            })
            # exe не даёт детекта — установщик может класть файлы куда угодно

        elif t_id == "file":
            target = target_path or "{PLUGINS_DIR}"
            install_steps.append({
                "type": "copy_file",
                "source": source_path,
                "target": target,
            })
            # для детекта нужен полный путь к файлу
            detect.append({
                "type": "file_exists",
                "path": (target.rstrip("/\\") + "/" + filename) if filename else target,
            })

        elif t_id == "reg":
            install_steps.append({
                "type": "import_reg",
                "path": source_path,
            })
            # детект для .reg — пусто (без знания ключей не проверить)

    result = dict(custom_plugin)
    # Уважаем уже заданные install_steps/detect — не перезаписываем,
    # если их кто-то прописал вручную в custom_configs
    if "install_steps" not in result:
        result["install_steps"] = install_steps
    if "detect" not in result:
        result["detect"] = detect
    return result
