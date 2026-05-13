# -*- coding: utf-8 -*-
"""
plugin_checker.py
Миксин PluginCheckerMixin для AksiomInstaller — содержит логику работы с
файловой системой: поиск установленных плагинов, динамические пути,
удаление плагинов.

[AKSIOM-FIX #14] _has_relevant_files: ограничен по глубине вместо полного
os.walk (быстрее на больших каталогах, меньше шанс зависнуть на сетевых
дисках).
"""

from __future__ import annotations

import glob
import os
import re
import shutil

from PyQt6.QtWidgets import QMessageBox


# Расширения файлов плагинов AE — общая константа модуля,
# чтобы не дублировать кортежи в каждом методе.
_PLUGIN_EXTS = (
    ".aex", ".jsx", ".jsxbin", ".dll", ".exe",
    ".prm", ".lic", ".zxp", ".plugin",
)
_PLUGIN_EXTS_WITH_KEY = _PLUGIN_EXTS + (".key",)


class PluginCheckerMixin:
    """
    Миксин для AksiomInstaller. Подразумевает наличие следующих атрибутов:
      ae_drive, custom_install_path, custom_plugin_paths, plugin_keywords,
      plugins_data, custom_data, lang_dict, current_lang, old_rsmb.
    """

    # ------------------------------------------------------------------
    # Базовые пути
    # ------------------------------------------------------------------
    def get_pf(self) -> str:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        if self.ae_drive:
            pf = self.ae_drive + os.path.splitdrive(pf)[1]
        return pf

    def get_pf86(self) -> str:
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        if self.ae_drive:
            pf86 = self.ae_drive + os.path.splitdrive(pf86)[1]
        return pf86

    @staticmethod
    def extract_gdrive_id(url: str) -> str:
        if not url:
            return ""
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
        match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
        if "http" not in url and "/" not in url:
            return url
        return ""

    # ------------------------------------------------------------------
    # Динамические пути установки
    # ------------------------------------------------------------------
    def get_dynamic_paths(self, ae_version: str) -> tuple[str, str]:
        custom_path = (self.custom_install_path or "").strip()

        if custom_path and ae_version != "None":
            custom_path = re.sub(
                r"(?i)(After Effects\s*)20\d{2}",
                rf"\g<1>{ae_version}",
                custom_path,
            )

        pf = self.get_pf()
        base_dir = (
            custom_path
            if custom_path
            else os.path.join(pf, "Adobe", f"Adobe After Effects {ae_version}")
        )

        plugins_dir = (
            os.path.join(base_dir, "Support Files", "Plug-ins")
            if not custom_path
            else custom_path
        )
        scripts_dir = (
            os.path.join(base_dir, "Support Files", "Scripts", "ScriptUI Panels")
            if not custom_path
            else os.path.join(custom_path, "Scripts", "ScriptUI Panels")
        )

        return plugins_dir, scripts_dir

    def resolve_target_path(
        self, plugin_name: str, default_path: str, full_ae_version: str
    ) -> str:
        custom_path = self.custom_plugin_paths.get(plugin_name, "").strip()
        if custom_path:
            if full_ae_version != "None":
                custom_path = re.sub(
                    r"(?i)(After Effects\s*)20\d{2}",
                    rf"\g<1>{full_ae_version}",
                    custom_path,
                )
            return custom_path
        return default_path

    # ------------------------------------------------------------------
    # Поиск установленных плагинов
    # ------------------------------------------------------------------
    def get_search_dirs(self, ae_version: str) -> list[str]:
        pf = self.get_pf()
        pf86 = self.get_pf86()
        pd = os.environ.get("ProgramData", r"C:\ProgramData")

        dirs = [
            os.path.join(pf, "BorisFX", "ContinuumAE", "14", "lib"),
            os.path.join(pf, "BorisFX"),
            os.path.join(pf, "Maxon"),
            os.path.join(pf, "GenArts"),
            os.path.join(pf, "Red Giant"),
            os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore"),
            os.path.join(pf86, "Common Files", "Adobe", "CEP", "extensions"),
            os.path.join(pd, "GenArts"),
            os.path.join(pd, "VideoCopilot"),
            os.path.join(pd, "Maxon"),
            os.path.join(pd, "Red Giant"),
        ]
        plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)
        if os.path.exists(plugins_dir):
            dirs.append(plugins_dir)
        if os.path.exists(scripts_dir):
            dirs.append(scripts_dir)
        return dirs

    def _has_relevant_files(self, directory: str, max_depth: int = 4) -> bool:
        """
        [AKSIOM-FIX #14] Ограниченный по глубине обход вместо полного os.walk.
        Возвращает True при первом же релевантном файле (early-exit).
        """
        return self._scan_for_relevant_recursive(directory, _PLUGIN_EXTS, max_depth, 0)

    def _scan_for_relevant_recursive(
        self,
        directory: str,
        exts: tuple,
        max_depth: int,
        depth: int,
    ) -> bool:
        """[AKSIOM-FIX #14] Хелпер: рекурсивный обход с ранним выходом."""
        if depth > max_depth:
            return False
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            if entry.name.lower().endswith(exts):
                                return True
                        elif entry.is_dir(follow_symlinks=False):
                            if self._scan_for_relevant_recursive(
                                entry.path, exts, max_depth, depth + 1
                            ):
                                return True
                    except OSError:
                        continue
        except (PermissionError, OSError):
            pass
        return False

    def _fast_search(
        self,
        directory: str,
        plugin_name: str,
        keywords: list[str],
        max_depth: int = 4,
        current_depth: int = 0,
    ) -> bool:
        if current_depth > max_depth:
            return False
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    name_lower = entry.name.lower()

                    match_found = any(kw.lower() in name_lower for kw in keywords)
                    if (plugin_name == "Deep_Glow"
                            and "2" in name_lower and "deep" in name_lower):
                        match_found = False

                    if match_found:
                        if entry.is_file() and name_lower.endswith(_PLUGIN_EXTS[:-1] + (".zxp",)):
                            return True
                        elif entry.is_dir():
                            if self._has_relevant_files(entry.path):
                                return True

                    if entry.is_dir():
                        if self._fast_search(
                            entry.path, plugin_name, keywords,
                            max_depth, current_depth + 1,
                        ):
                            return True
        except (PermissionError, OSError):
            pass
        return False

    def is_plugin_installed(self, plugin_name: str, ae_version: str) -> bool:
        search_dirs: list[str] = []
        has_custom = False

        custom_main_path = self.custom_plugin_paths.get(plugin_name, "").strip()
        if custom_main_path:
            search_dirs.append(self.resolve_target_path(plugin_name, "", ae_version))
            has_custom = True

        if plugin_name in self.custom_data:
            c_files = self.custom_data[plugin_name].get("custom_files", {})
            plugins_dir, _scripts_dir = self.get_dynamic_paths(ae_version)
            custom_install_path = (self.custom_install_path or "").strip()

            if custom_install_path and ae_version != "None":
                custom_install_path = re.sub(
                    r"(?i)(After Effects\s*)20\d{2}",
                    rf"\g<1>{ae_version}",
                    custom_install_path,
                )

            for t_id, p in c_files.items():
                target_path = p.get("target_path", "")

                if target_path and ae_version != "None":
                    target_path = re.sub(
                        r"(?i)(After Effects\s*)20\d{2}",
                        rf"\g<1>{ae_version}",
                        target_path,
                    )

                if target_path:
                    search_dirs.append(target_path)
                    has_custom = True

                if t_id == "file":
                    dest_dir = target_path if target_path else plugins_dir
                    filename = p.get("filename", "")
                    if filename and os.path.exists(os.path.join(dest_dir, filename)):
                        return True

                if t_id == "zip":
                    extract_target = target_path if target_path else (
                        custom_install_path
                        if custom_install_path
                        else os.path.join(plugins_dir, plugin_name)
                    )
                    if (os.path.exists(extract_target)
                            and os.path.basename(extract_target).lower() == plugin_name.lower()):
                        try:
                            with os.scandir(extract_target) as it:
                                if any(True for _ in it):
                                    return True
                        except OSError:
                            pass

        if not has_custom:
            search_dirs = self.get_search_dirs(ae_version)
        keywords = self.plugin_keywords.get(plugin_name, [plugin_name.lower()])

        for d in {d for d in search_dirs if os.path.exists(d)}:
            if self._fast_search(d, plugin_name, keywords):
                return True

        pd = os.environ.get("ProgramData", r"C:\ProgramData")
        if (not has_custom and plugin_name == "Sapphire"
                and glob.glob(os.path.join(pd, "GenArts", "rlm", "*.lic"))):
            return True

        return False

    # ------------------------------------------------------------------
    # Удаление плагинов
    # ------------------------------------------------------------------
    def uninstall_plugin(self, plugin_name: str, ae_version: str) -> bool:
        exe_installers = ["BCC", "Mocha_Pro", "Sapphire", "RedGiant"]

        if plugin_name == "RSMB" and not self.old_rsmb:
            exe_installers.append("RSMB")

        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])

        if plugin_name in exe_installers:
            QMessageBox.warning(
                None,
                t.get("warn_title", "Warning"),
                t.get("un_warn_exe", "Uninstall this using Windows Control Panel."),
            )
            return False

        try:
            search_dirs: list[str] = []
            deleted_something = False

            custom_main_path = self.custom_plugin_paths.get(plugin_name, "").strip()
            if custom_main_path:
                search_dirs.append(self.resolve_target_path(plugin_name, "", ae_version))

            if plugin_name in self.custom_data:
                c_files = self.custom_data[plugin_name].get("custom_files", {})
                plugins_dir, _scripts_dir = self.get_dynamic_paths(ae_version)
                custom_install_path = (self.custom_install_path or "").strip()

                if custom_install_path and ae_version != "None":
                    custom_install_path = re.sub(
                        r"(?i)(After Effects\s*)20\d{2}",
                        rf"\g<1>{ae_version}",
                        custom_install_path,
                    )

                for t_id, f_info in c_files.items():
                    target_dir = f_info.get("target_path", "")

                    if target_dir and ae_version != "None":
                        target_dir = re.sub(
                            r"(?i)(After Effects\s*)20\d{2}",
                            rf"\g<1>{ae_version}",
                            target_dir,
                        )

                    if not target_dir:
                        if t_id == "zip":
                            target_dir = (
                                custom_install_path
                                if custom_install_path
                                else os.path.join(plugins_dir, plugin_name)
                            )
                        elif t_id in ("exe", "file"):
                            target_dir = plugins_dir

                    if target_dir:
                        search_dirs.append(target_dir)

                    filename = f_info.get("filename")

                    if t_id == "zip":
                        if target_dir and os.path.exists(target_dir):
                            folder_name = os.path.basename(os.path.normpath(target_dir))
                            if plugin_name.lower() == folder_name.lower():
                                shutil.rmtree(target_dir, ignore_errors=True)
                                deleted_something = True
                    elif target_dir and filename:
                        full_path = os.path.join(target_dir, filename)
                        if os.path.exists(full_path):
                            if os.path.isdir(full_path):
                                shutil.rmtree(full_path, ignore_errors=True)
                            else:
                                os.remove(full_path)
                            deleted_something = True

            search_dirs.extend(self.get_search_dirs(ae_version))

            keywords = self.plugin_keywords.get(plugin_name, [plugin_name.lower()])

            for d in {d for d in search_dirs if os.path.exists(d)}:
                try:
                    with os.scandir(d) as it:
                        for entry in it:
                            name_lower = entry.name.lower()

                            match_found = any(kw.lower() in name_lower for kw in keywords)

                            if match_found:
                                if (plugin_name == "Deep_Glow"
                                        and "2" in name_lower and "deep" in name_lower):
                                    continue
                                if entry.is_dir():
                                    if not self._has_relevant_files(entry.path):
                                        if hasattr(self, "log"):
                                            self.log(
                                                f"   ⚠ Пропуск: '{entry.path}' "
                                                f"(нет файлов плагинов внутри)",
                                                f"   ⚠ Skip: '{entry.path}' "
                                                f"(no plugin files inside)",
                                            )
                                        continue
                                    shutil.rmtree(entry.path, ignore_errors=True)
                                else:
                                    if not name_lower.endswith(_PLUGIN_EXTS_WITH_KEY):
                                        continue
                                    try:
                                        os.remove(entry.path)
                                    except OSError:
                                        continue
                                deleted_something = True
                except (PermissionError, OSError) as exc:
                    if hasattr(self, "log"):
                        self.log(
                            f"Ошибка обхода {d} при удалении: {exc}",
                            f"Error scanning {d} while uninstalling: {exc}",
                        )

            return deleted_something

        except Exception as exc:  # noqa: BLE001
            if hasattr(self, "log"):
                self.log(
                    f"Ошибка при удалении {plugin_name}: {exc}",
                    f"Error uninstalling {plugin_name}: {exc}",
                )
            return False
