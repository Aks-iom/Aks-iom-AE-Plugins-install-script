# -*- coding: utf-8 -*-
"""
installer_logic.py
Миксин InstallerLogicMixin для AksiomInstaller — содержит всю логику
скачивания и установки плагинов.

Включает:
  - GdownLogCatcher — перехват прогресса gdown через подмену sys.stderr
  - download_from_gdrive
  - verify_archive_integrity
  - _ensure_downloaded
  - execute_native_install (per-plugin if/elif блок)
  - _perform_installation
  - run_install_process
  - start_installation

Применённые фиксы:
  [AKSIOM-FIX #3] Корректная обработка subprocess в Mocha_Pro / Universe / Trapcode / MBS
                  (whitelist кодов 0 и 3010, отлов CalledProcessError)
  [AKSIOM-FIX #7] RSMB: check=False вместо check=True (cancel пользователем не ронял)
  [AKSIOM-FIX #8] Кэширование plugins.json по mtime (одно чтение вместо N)
  [AKSIOM-FIX #10] verify_archive_integrity: лог через self.log + удаление битого zip
  [AKSIOM-FIX #19] Валидация gdrive_id (отлов плейсхолдеров до запроса)
  [AKSIOM-FIX #23] Однократная подмена AE-версии на уровне pipeline
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile

try:
    import gdown  # type: ignore
except ImportError:
    gdown = None

try:
    import winreg  # type: ignore
except ImportError:
    winreg = None

from PyQt6.QtCore import QTimer

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_GDOWN_STDERR_LOCK = threading.Lock()

# [AKSIOM-FIX #3] Коды успеха Windows-инсталлеров (InstallShield/Inno Setup):
#   0    — успех
#   3010 — успех, требуется перезагрузка
_INSTALLER_SUCCESS_CODES = {0, 3010}

# [AKSIOM-FIX #19] Минимальная валидация Google Drive ID
_GDRIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")


def _is_valid_gdrive_id(file_id: str) -> bool:
    """[AKSIOM-FIX #19] Защита от плейсхолдеров вроде PLACEHOLDER_*."""
    if not file_id:
        return False
    if file_id.startswith("PLACEHOLDER"):
        return False
    return bool(_GDRIVE_ID_RE.match(file_id))


# ---------------------------------------------------------------------------
# GdownLogCatcher
# ---------------------------------------------------------------------------
class GdownLogCatcher:
    def __init__(
        self,
        ui_app,
        original_stderr,
        current_index: int,
        total_plugins: int,
        plugin_name: str,
    ) -> None:
        self.ui_app = ui_app
        self.original_stderr = original_stderr
        self.current_index = current_index
        self.total_plugins = total_plugins
        self.plugin_name = plugin_name
        self.last_percent = -1

    def write(self, text: str) -> None:
        if self.original_stderr:
            try:
                self.original_stderr.write(text)
                self.original_stderr.flush()
            except Exception:  # noqa: BLE001
                pass

        if not text or "%" not in text:
            return

        match = re.search(r"(\d+)%", text)
        if match:
            percent = int(match.group(1))
            if percent != self.last_percent and (percent % 5 == 0 or percent == 100):
                self.last_percent = percent
                self.ui_app._update_last_log_line(
                    f"Загрузка {self.plugin_name}: {percent}%",
                    f"Downloading {self.plugin_name}: {percent}%",
                )
                base_prog = self.current_index / self.total_plugins
                chunk_prog = (percent / 100) * (1 / self.total_plugins)
                self.ui_app.signals.progress_value.emit(base_prog + chunk_prog)

    def flush(self) -> None:
        if self.original_stderr:
            try:
                self.original_stderr.flush()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Миксин с бизнес-логикой установки
# ---------------------------------------------------------------------------
class InstallerLogicMixin:
    """См. модульный docstring."""

    # [AKSIOM-FIX #8] Кэш plugins.json: (path → (mtime, parsed_dict))
    _PLUGINS_JSON_CACHE: dict[str, tuple[float, dict]] = {}

    # ------------------------------------------------------------------
    # Загрузка с Google Drive
    # ------------------------------------------------------------------
    def download_from_gdrive(
        self,
        file_id: str,
        destination_path: str,
        plugin_name: str = "Plugin",
        current_index: int = 0,
        total_plugins: int = 1,
    ) -> bool:
        # [AKSIOM-FIX #19] Валидация id до сетевого запроса
        if not _is_valid_gdrive_id(file_id):
            self.log(
                f"❌ Невалидный Google Drive ID для {plugin_name} "
                f"(возможно, плейсхолдер). Загрузка отменена.",
                f"❌ Invalid Google Drive ID for {plugin_name} "
                f"(possibly placeholder). Download skipped.",
            )
            return False
        if gdown is None:
            self.log(
                "❌ gdown не установлен — скачивание невозможно.",
                "❌ gdown not installed — cannot download.",
            )
            return False

        try:
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            self.log(
                f"[*] Запуск загрузки {plugin_name} (Google Drive через gdown)...",
                f"[*] Starting download {plugin_name} (Google Drive via gdown)...",
            )

            original_stderr = sys.stderr
            catcher = GdownLogCatcher(
                self, original_stderr, current_index, total_plugins, plugin_name
            )
            with _GDOWN_STDERR_LOCK:
                sys.stderr = catcher
                try:
                    gdown.download(id=file_id, output=destination_path, quiet=False)
                finally:
                    sys.stderr = original_stderr

            if os.path.exists(destination_path):
                self.log(
                    f"[+] Файл {plugin_name} успешно скачан.",
                    f"[+] File {plugin_name} successfully downloaded.",
                )
                return True
            self.log(
                f"❌ Ошибка скачивания {plugin_name}: файл не был создан.",
                f"❌ Error downloading {plugin_name}: file was not created.",
            )
            return False

        except Exception as exc:  # noqa: BLE001
            self.log(
                f"❌ Системная ошибка при скачивании {plugin_name}: {exc}",
                f"❌ System Error during download of {plugin_name}: {exc}",
            )
            return False

    # ------------------------------------------------------------------
    # Проверка целостности архива
    # ------------------------------------------------------------------
    def verify_archive_integrity(
        self, zip_path: str, expected_md5: str | None = None
    ) -> bool:
        """[AKSIOM-FIX #10] Логи через self.log, удаление битого zip."""
        if expected_md5:
            hash_md5 = hashlib.md5()
            try:
                with open(zip_path, "rb") as f:
                    for chunk in iter(lambda: f.read(1048576), b""):
                        hash_md5.update(chunk)
            except OSError as exc:
                self.log(
                    f"⚠️ Ошибка чтения MD5 для {zip_path}: {exc}",
                    f"⚠️ MD5 read error for {zip_path}: {exc}",
                )
                return False
            if hash_md5.hexdigest() != expected_md5:
                self.log(
                    f"⚠️ MD5 не совпал для {zip_path} — файл будет перекачан.",
                    f"⚠️ MD5 mismatch for {zip_path} — will be re-downloaded.",
                )
                # [AKSIOM-FIX #10] Удаляем битый файл
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
                return False
        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                bad = z.testzip()
                if bad:
                    self.log(
                        f"⚠️ Архив повреждён ({bad}): {zip_path}",
                        f"⚠️ Archive corrupted ({bad}): {zip_path}",
                    )
                    try:
                        os.remove(zip_path)
                    except OSError:
                        pass
                    return False
                return True
        except zipfile.BadZipFile:
            self.log(
                f"⚠️ Не валидный zip: {zip_path}",
                f"⚠️ Not a valid zip: {zip_path}",
            )
            try:
                os.remove(zip_path)
            except OSError:
                pass
            return False
        except OSError as exc:
            self.log(
                f"⚠️ Ошибка ФС при проверке архива: {exc}",
                f"⚠️ FS error checking archive: {exc}",
            )
            return False

    # ------------------------------------------------------------------
    # _ensure_downloaded (без изменений в логике, только мелкие правки)
    # ------------------------------------------------------------------
    def _ensure_downloaded(self, plugin_name: str, index: int, total: int) -> bool:
        plugin_info = next((p for p in self.plugins_data if p[0] == plugin_name), None)
        if not plugin_info:
            return False

        _, _, bat_path, _needs_version, _, expected_md5 = plugin_info
        is_custom = plugin_name in self.custom_data
        success = True

        if is_custom:
            c_files = self.custom_data[plugin_name].get("custom_files", {})
            for _t_id, f_info in c_files.items():
                c_source = f_info.get("source")
                c_filename = f_info.get("filename")
                target_file_path = os.path.join(self.base_dir, c_filename or "")
                if c_source == "gdrive" and not os.path.exists(target_file_path):
                    if not self.download_from_gdrive(
                        f_info.get("gdrive_id", ""), target_file_path,
                        plugin_name, index, total,
                    ):
                        success = False
                if not os.path.exists(target_file_path):
                    success = False
        else:
            plugin_src_dir = os.path.dirname(os.path.join(self.base_dir, bat_path))
            zip_path = os.path.join(self.base_dir, f"{plugin_name}.zip")

            if not os.path.exists(plugin_src_dir):
                if (not os.path.exists(zip_path)
                        or not self.verify_archive_integrity(zip_path, expected_md5)):
                    if not self.download_from_gdrive(
                        self.gdrive_file_ids.get(plugin_name, ""), zip_path,
                        plugin_name, index, total,
                    ):
                        success = False

                if (success and os.path.exists(zip_path)
                        and self.verify_archive_integrity(zip_path, expected_md5)):
                    self.log(
                        f"[*] Распаковка {plugin_name}...",
                        f"[*] Extracting {plugin_name}...",
                    )
                    try:
                        with zipfile.ZipFile(zip_path, "r") as zip_ref:
                            zip_ref.extractall(self.base_dir)
                    except Exception as exc:  # noqa: BLE001
                        self.log(
                            f"❌ Ошибка распаковки {plugin_name}: {exc}",
                            f"❌ Error extracting {plugin_name}: {exc}",
                        )
                        success = False
                    finally:
                        try:
                            os.remove(zip_path)
                        except OSError:
                            pass
                elif not os.path.exists(plugin_src_dir):
                    success = False
        return success

    # ==================================================================
    # [AKSIOM-FIX #3] Хелпер для безопасного запуска инсталлеров
    # ==================================================================
    @staticmethod
    def _run_installer(
        cmd: list[str],
        *,
        success_codes: set[int] | None = None,
        creationflags: int = CREATE_NO_WINDOW,
        check_silent: bool = True,
    ) -> int:
        """
        [AKSIOM-FIX #3] Запускает .exe-инсталлер. Коды 0 и 3010 (требуется
        перезагрузка) считаются успехом. Возвращает фактический returncode.
        Бросает CalledProcessError только если returncode не в whitelist.
        """
        codes = success_codes if success_codes is not None else _INSTALLER_SUCCESS_CODES
        proc = subprocess.run(cmd, check=False, creationflags=creationflags)
        if proc.returncode not in codes:
            if check_silent:
                raise subprocess.CalledProcessError(proc.returncode, cmd)
        return proc.returncode

    # ==================================================================
    # execute_native_install
    # ==================================================================
    def execute_native_install(
        self, plugin_name: str, ae_version: str, src_dir: str
    ) -> None:
        plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)
        pf = self.get_pf()
        pf86 = self.get_pf86()
        pd = os.environ.get("ProgramData", r"C:\ProgramData")

        if plugin_name == "BCC":
            self._run_installer(
                [os.path.join(src_dir, "BCC_Setup.exe"),
                 "/s", "/v/qb", "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            )
            bcc_lib = os.path.join(pf, "BorisFX", "ContinuumAE", "14", "lib")
            os.makedirs(bcc_lib, exist_ok=True)
            shutil.copy2(
                os.path.join(src_dir, "Crack", "Continuum_Common_AE.dll"), bcc_lib
            )
            shutil.copytree(
                os.path.join(src_dir, "Crack", "GenArts"),
                os.path.join(pd, "GenArts"),
                dirs_exist_ok=True,
            )

        elif plugin_name == "Bokeh":
            dest = self.resolve_target_path(
                plugin_name, os.path.join(plugins_dir, "Plugins Everything"), ae_version
            )
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Bokeh.aex"), dest)

        elif plugin_name == "Deep_Glow":
            dest = self.resolve_target_path(
                plugin_name,
                os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore"),
                ae_version,
            )
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Deep Glow.aex"), dest)

        elif plugin_name == "Deep_Glow2":
            dest = self.resolve_target_path(
                plugin_name,
                os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore"),
                ae_version,
            )
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "DeepGlow2.aex"), dest)
            shutil.copy2(os.path.join(src_dir, "IrisBlurSDK.dll"), dest)

        elif plugin_name == "Element":
            dest_plugin = self.resolve_target_path(
                plugin_name, os.path.join(plugins_dir, "VideoCopilot"), ae_version
            )
            dest_lic = os.path.join(pd, "VideoCopilot")
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
            dest_docs = os.path.join(buf.value, "VideoCopilot")
            os.makedirs(dest_plugin, exist_ok=True)
            os.makedirs(dest_lic, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Element.aex"), dest_plugin)
            shutil.copy2(os.path.join(src_dir, "element2_license"), dest_lic)
            shutil.copytree(
                os.path.join(src_dir, "VideoCopilot"), dest_docs, dirs_exist_ok=True
            )

        elif plugin_name == "Fast_Layers":
            dest = self.resolve_target_path(plugin_name, scripts_dir, ae_version)
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Fast_Layers.jsx"), dest)

        elif plugin_name == "Flow":
            dest = self.resolve_target_path(
                plugin_name,
                os.path.join(pf86, "Common Files", "Adobe", "CEP", "extensions", "flow"),
                ae_version,
            )
            src_flow = os.path.join(src_dir, "flow-v1.5.2")
            if os.path.exists(src_flow):
                shutil.copytree(src_flow, dest, dirs_exist_ok=True)

            if winreg is not None:
                for csxs in ("CSXS.10", "CSXS.11", "CSXS.12", "CSXS.13",
                             "CSXS.14", "CSXS.15", "CSXS.16"):
                    try:
                        access = winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
                        with winreg.CreateKeyEx(
                            winreg.HKEY_LOCAL_MACHINE,
                            rf"Software\Adobe\{csxs}", 0, access,
                        ) as key:
                            winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
                    except OSError as exc:
                        self.log(
                            f"⚠️ Не удалось записать CEP debug в {csxs}: {exc}",
                            f"⚠️ Failed to write CEP debug to {csxs}: {exc}",
                        )

        elif plugin_name in ("Fxconsole", "Glitchify", "Saber"):
            dest = self.resolve_target_path(
                plugin_name, os.path.join(plugins_dir, "VideoCopilot"), ae_version
            )
            os.makedirs(dest, exist_ok=True)
            filename = "FXConsole" if plugin_name == "Fxconsole" else plugin_name
            shutil.copy2(os.path.join(src_dir, f"{filename}.aex"), dest)

        elif plugin_name == "Mocha_Pro":
            # [AKSIOM-FIX #3] Через _run_installer с whitelist 0, 3010
            self._run_installer(
                [os.path.join(src_dir, "mochapro_2026.0.1_adobe_installer.exe"),
                 "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            )
            time.sleep(4)
            subprocess.run(
                ["taskkill", "/F", "/IM", "mochapro.exe", "/T"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )

        elif plugin_name == "Influx":
            dest = self.resolve_target_path(
                plugin_name,
                os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0",
                             "MediaCore", "Autokroma Influx"),
                ae_version,
            )
            os.makedirs(dest, exist_ok=True)
            src_influx = os.path.join(src_dir, "Autokroma Influx")
            if os.path.exists(src_influx):
                shutil.copytree(src_influx, dest, dirs_exist_ok=True)
            else:
                shutil.copytree(src_dir, dest, dirs_exist_ok=True)

        elif plugin_name == "RSMB":
            if self.old_rsmb:
                dest = self.resolve_target_path(
                    plugin_name,
                    os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0",
                                 "MediaCore", "RSMB"),
                    ae_version,
                )
                os.makedirs(dest, exist_ok=True)
                for aex in glob.glob(os.path.join(src_dir, "*.aex")):
                    shutil.copy2(aex, dest)
            else:
                exe_files = glob.glob(os.path.join(src_dir, "*.exe"))
                if exe_files:
                    installer_path = exe_files[0]
                    self.log(
                        "[*] Запуск установщика RSMB. Пожалуйста, пройдите установку "
                        "в появившемся окне...",
                        "[*] Starting RSMB installer. Please complete the setup "
                        "in the window...",
                    )
                    # [AKSIOM-FIX #7] check=False — пользователь может Cancel'нуть, это норма
                    proc = subprocess.run([installer_path], check=False)
                    if proc.returncode not in _INSTALLER_SUCCESS_CODES:
                        self.log(
                            f"⚠️ Установка RSMB прервана пользователем (код {proc.returncode}).",
                            f"⚠️ RSMB installation cancelled by user (code {proc.returncode}).",
                        )
                else:
                    raise FileNotFoundError(
                        f"Установочный .exe файл для RSMB не найден в {src_dir}"
                    )

        elif plugin_name == "Sapphire":
            try:
                self._run_installer(
                    [os.path.join(src_dir, "sapphire_ae_install.exe"),
                     "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                )
            except subprocess.CalledProcessError as exc:
                # Sapphire-specific: уже учитывается в _INSTALLER_SUCCESS_CODES
                # но оставляем явный re-raise для совместимости
                if exc.returncode != 3010:
                    raise

        elif plugin_name == "Shake_Generator":
            dest = self.resolve_target_path(plugin_name, scripts_dir, ae_version)
            os.makedirs(dest, exist_ok=True)
            for jsx in glob.glob(os.path.join(src_dir, "*.jsx")):
                shutil.copy2(jsx, dest)

        elif plugin_name == "Textevo2":
            dest = self.resolve_target_path(plugin_name, scripts_dir, ae_version)
            os.makedirs(dest, exist_ok=True)
            for jsxbin in glob.glob(os.path.join(src_dir, "*.jsxbin")):
                shutil.copy2(jsxbin, dest)

        elif plugin_name == "Twich":
            dest = self.resolve_target_path(
                plugin_name, os.path.join(plugins_dir, "VideoCopilot"), ae_version
            )
            os.makedirs(dest, exist_ok=True)
            for aex in glob.glob(os.path.join(src_dir, "*.aex")):
                shutil.copy2(aex, dest)
            for key_file in glob.glob(os.path.join(src_dir, "*.key")):
                shutil.copy2(key_file, dest)

        elif plugin_name == "Twixtor":
            dest = self.resolve_target_path(
                plugin_name,
                os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0",
                             "MediaCore", "Twixtor8AE"),
                ae_version,
            )
            os.makedirs(dest, exist_ok=True)
            src_twixtor = os.path.join(src_dir, "Twixtor8AE")
            if os.path.exists(src_twixtor):
                shutil.copytree(src_twixtor, dest, dirs_exist_ok=True)

        elif plugin_name == "Uwu2x":
            cep_base = self.resolve_target_path(
                plugin_name,
                os.path.join(pf86, "Common Files", "Adobe", "CEP", "extensions"),
                ae_version,
            )
            os.makedirs(cep_base, exist_ok=True)
            src_pro = os.path.join(src_dir, "uwu2x-pro")
            src_norm = os.path.join(src_dir, "uwu2x")
            if os.path.exists(src_pro):
                shutil.copytree(
                    src_pro, os.path.join(cep_base, "uwu2x-pro"), dirs_exist_ok=True
                )
            elif os.path.exists(src_norm):
                shutil.copytree(
                    src_norm, os.path.join(cep_base, "uwu2x"), dirs_exist_ok=True
                )

            if winreg is not None:
                for csxs in ("CSXS.10", "CSXS.11", "CSXS.12", "CSXS.13",
                             "CSXS.14", "CSXS.15", "CSXS.16"):
                    try:
                        access = winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
                        with winreg.CreateKeyEx(
                            winreg.HKEY_LOCAL_MACHINE,
                            rf"Software\Adobe\{csxs}", 0, access,
                        ) as key:
                            winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
                    except OSError as exc:
                        self.log(
                            f"⚠️ Не удалось записать CEP debug в {csxs}: {exc}",
                            f"⚠️ Failed to write CEP debug to {csxs}: {exc}",
                        )

        elif plugin_name == "Prime_tool":
            cep_path = self.resolve_target_path(
                plugin_name,
                os.path.join(pf86, "Common Files", "Adobe", "CEP",
                             "extensions", "com.PrimeTools"),
                ae_version,
            )
            os.makedirs(cep_path, exist_ok=True)
            zxp_file = os.path.join(src_dir, "com.PrimeTools.cep.zxp")
            if os.path.exists(zxp_file):
                with zipfile.ZipFile(zxp_file, "r") as zip_ref:
                    zip_ref.extractall(cep_path)

        elif plugin_name == "RedGiant":
            if self.rg_maxon_app:
                maxon_installer = os.path.join(src_dir, "1_Maxon.exe")
                if os.path.exists(maxon_installer):
                    self._run_installer(
                        [maxon_installer, "--mode", "unattended",
                         "--unattendedmodeui", "minimal"],
                    )

            if self.rg_plugin_only:
                rg_installer = os.path.join(src_dir, "2_RedGiant.exe")
                unlocker = os.path.join(src_dir, "3_Unlocker.exe")
                if os.path.exists(rg_installer):
                    self._run_installer(
                        [rg_installer, "--mode", "unattended",
                         "--unattendedmodeui", "minimal"],
                    )
                if os.path.exists(unlocker):
                    self._run_installer([unlocker, "/SILENT"])

            time.sleep(6)
            subprocess.run(
                ["taskkill", "/F", "/IM", "Maxon App.exe", "/T"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )

        elif plugin_name in ("Universe", "Trapcode", "MBS"):
            run_shared = bool(getattr(self, "_rg_run_shared_steps", True))

            if plugin_name == "Universe":
                maxon_exe = os.path.join(src_dir, "MaxonApp.exe")
                activation_exe = os.path.join(src_dir, "Unlocker.exe")
                plugin_exe = os.path.join(src_dir, "2Universe_Installer.exe")
            else:
                maxon_exe = os.path.join(src_dir, "1_Maxon.exe")
                activation_exe = os.path.join(src_dir, "2_Activation.exe")
                plugin_exe = os.path.join(src_dir, f"3_{plugin_name}.exe")

            # Шаг 1: Maxon App
            if run_shared and os.path.exists(maxon_exe):
                self.log(
                    f"[*] {plugin_name}: установка Maxon App ({os.path.basename(maxon_exe)})...",
                    f"[*] {plugin_name}: installing Maxon App ({os.path.basename(maxon_exe)})...",
                )
                # [AKSIOM-FIX #3] Через _run_installer
                self._run_installer([maxon_exe], creationflags=0)
            elif not run_shared:
                self.log(
                    f"[*] {plugin_name}: пропуск Maxon App (уже установлен в этой сессии).",
                    f"[*] {plugin_name}: skipping Maxon App (already installed this session).",
                )

            # Шаг 2: Activation
            if run_shared and os.path.exists(activation_exe):
                self.log(
                    f"[*] {plugin_name}: запуск активации ({os.path.basename(activation_exe)})...",
                    f"[*] {plugin_name}: running activation ({os.path.basename(activation_exe)})...",
                )
                self._run_installer([activation_exe], creationflags=0)
            elif not run_shared:
                self.log(
                    f"[*] {plugin_name}: пропуск активации (уже выполнена в этой сессии).",
                    f"[*] {plugin_name}: skipping activation (already done this session).",
                )

            # Шаг 3: сам плагин
            if os.path.exists(plugin_exe):
                self.log(
                    f"[*] {plugin_name}: запуск установщика плагина ({os.path.basename(plugin_exe)})...",
                    f"[*] {plugin_name}: running plugin installer ({os.path.basename(plugin_exe)})...",
                )
                self._run_installer([plugin_exe], creationflags=0)
            else:
                raise FileNotFoundError(
                    f"Установочный exe для {plugin_name} не найден: {plugin_exe}"
                )

            time.sleep(4)
            subprocess.run(
                ["taskkill", "/F", "/IM", "Maxon App.exe", "/T"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )

    # ==================================================================
    # _perform_installation — маршрутизирует через PluginPipeline.
    # ==================================================================
    def _perform_installation(
        self,
        plugin_name: str,
        index: int,
        total: int,
        ae_version: str,
        custom_install_path: str,
    ) -> None:
        plugin_info = next((p for p in self.plugins_data if p[0] == plugin_name), None)
        if not plugin_info:
            return
        _, _, bat_path, _needs_version, _, _expected_md5 = plugin_info
        is_custom = plugin_name in self.custom_data

        # [AKSIOM-FIX #23] Подмену версии в custom_install_path делает pipeline
        # через build_default_paths. Здесь её не повторяем — pipeline получит
        # raw-значение и сам подставит.

        plugin_full = None
        if is_custom:
            plugin_full = dict(self.custom_data.get(plugin_name, {}))
        else:
            plugin_full = self._lookup_native_plugin_meta(plugin_name)

        if plugin_full is None:
            self.log(
                f"❌ Не найдено описание плагина {plugin_name}.",
                f"❌ Plugin description not found for {plugin_name}.",
            )
            return

        pipeline = self._get_or_create_pipeline()
        pipeline.update_settings(
            ae_drive=self.ae_drive,
            custom_install_path=custom_install_path,
            options=self._build_options_dict(),
        )

        if is_custom:
            src_dir = self.base_dir
        elif bat_path and bat_path != "CUSTOM":
            src_dir = os.path.dirname(os.path.join(self.base_dir, bat_path))
        else:
            src_dir = self.base_dir

        custom_path = self.custom_plugin_paths.get(plugin_name, "").strip() or None

        try:
            pipeline.install(plugin_full, ae_version, src_dir, custom_path)
        except Exception as exc:  # noqa: BLE001
            self.log(
                f"❌ Ошибка установки {plugin_name}: {exc}",
                f"❌ Error installing {plugin_name}: {exc}",
            )

    # ------------------------------------------------------------------
    # Помощники
    # ------------------------------------------------------------------
    def _lookup_native_plugin_meta(self, plugin_name: str) -> dict | None:
        """
        [AKSIOM-FIX #8] Кэшируем содержимое plugins.json по mtime.
        Файл небольшой, но parse JSON'а на каждый вызов — overkill.
        """
        local_db_path = os.path.join(self.base_dir, "plugins.json")
        try:
            mtime = os.path.getmtime(local_db_path)
        except OSError:
            return None

        cache = type(self)._PLUGINS_JSON_CACHE
        cached = cache.get(local_db_path)
        if cached is None or cached[0] != mtime:
            try:
                with open(local_db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                return None
            cache[local_db_path] = (mtime, data)
        else:
            data = cached[1]

        for p in data.get("plugins", []):
            if p.get("name") == plugin_name:
                return p
        return None

    def _build_options_dict(self) -> dict:
        return {
            "old_rsmb": bool(self.old_rsmb),
            "rg_plugin_only": bool(self.rg_plugin_only),
            "rg_maxon_app": bool(self.rg_maxon_app),
            "force_install": bool(self.force_install),
        }

    # ------------------------------------------------------------------
    # Поиск активатора Maxon
    # ------------------------------------------------------------------
    def find_maxon_activator(self) -> tuple[str, str] | None:
        candidates: list[tuple[str, str]] = [
            ("Universe", os.path.join(self.base_dir, "Universe", "Unlocker.exe")),
            ("Trapcode", os.path.join(self.base_dir, "Trapcode", "2_Activation.exe")),
            ("MBS",      os.path.join(self.base_dir, "MBS", "2_Activation.exe")),
            ("RedGiant", os.path.join(self.base_dir, "RedGiant", "3_Unlocker.exe")),
        ]
        for plugin_name, exe_path in candidates:
            if os.path.exists(exe_path):
                return exe_path, plugin_name
        return None

    def run_maxon_activator(self) -> tuple[bool, str]:
        t = self.lang_dict.get(self.current_lang, self.lang_dict.get("en", {}))
        found = self.find_maxon_activator()
        if not found:
            return False, t.get(
                "maxon_activation_not_found",
                "Maxon activator not found. Install at least one of: "
                "RedGiant, Universe, Trapcode or MBS first.",
            )
        exe_path, plugin_name = found
        try:
            # GUI-инсталлер — не суём CREATE_NO_WINDOW (окно нужно).
            # stdout/stderr закрываем, чтобы случайный print в активаторе
            # не сломал наш UI-stdout.
            subprocess.Popen(
                [exe_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            tmpl = t.get(
                "maxon_activation_error",
                "Failed to launch activator: {err}",
            )
            return False, tmpl.format(err=exc)
        tmpl = t.get(
            "maxon_activation_running",
            "Running Maxon activation ({plugin}). Complete it in the opened window.",
        )
        return True, tmpl.format(plugin=plugin_name)

    def _get_or_create_pipeline(self):
        if getattr(self, "_pipeline", None) is not None:
            return self._pipeline
        from core.installer import PluginPipeline

        installed_dir = os.path.join(self.base_dir, "installed")
        os.makedirs(installed_dir, exist_ok=True)

        def _download(file_id, dest, plugin_name, idx, total):
            return self.download_from_gdrive(file_id, dest, plugin_name, idx, total)

        def _extract(zip_path, target_dir):
            try:
                os.makedirs(target_dir, exist_ok=True)
                with zipfile.ZipFile(zip_path, "r") as z:
                    z.extractall(target_dir)
                return True
            except Exception as exc:  # noqa: BLE001
                self.log(
                    f"❌ Ошибка распаковки {zip_path}: {exc}",
                    f"❌ Error extracting {zip_path}: {exc}",
                )
                return False

        def _legacy_install(plugin_dict, context):
            try:
                self.execute_native_install(
                    plugin_dict.get("name", ""),
                    context.ae_version,
                    context.src_dir,
                )
                return True
            except Exception as exc:  # noqa: BLE001
                self.log(
                    f"❌ legacy execute_native_install: {exc}",
                    f"❌ legacy execute_native_install: {exc}",
                )
                return False

        def _legacy_uninstall(plugin_name, ae_version):
            return self._legacy_uninstall_by_keywords(plugin_name, ae_version)

        self._pipeline = PluginPipeline(
            cache_dir=self.base_dir,
            installed_dir=installed_dir,
            ae_drive=self.ae_drive,
            custom_install_path=(self.custom_install_path or "").strip(),
            options=self._build_options_dict(),
            logger=self.log,
            legacy_install=_legacy_install,
            legacy_uninstall=_legacy_uninstall,
            download_fn=_download,
            extract_fn=_extract,
        )
        return self._pipeline

    def _legacy_uninstall_by_keywords(self, plugin_name: str, ae_version: str) -> bool:
        from plugin_checker import PluginCheckerMixin
        return PluginCheckerMixin.uninstall_plugin(self, plugin_name, ae_version)

    # ==================================================================
    # run_install_process
    # ==================================================================
    def run_install_process(
        self,
        ae_version: str,
        selected_plugins: list[str],
        custom_install_path: str,
    ) -> None:
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
        try:
            total = len(selected_plugins)
            download_events = {name: threading.Event() for name in selected_plugins}
            download_results: dict[str, bool] = {name: False for name in selected_plugins}
            # [AKSIOM-FIX #4 partial] Лок для безопасных записей в download_results
            results_lock = threading.Lock()

            _rg_group = {"Universe", "Trapcode", "MBS"}
            _rg_leader = next(
                (n for n in selected_plugins if n in _rg_group), None
            )

            def download_task(name: str, idx: int) -> None:
                try:
                    res = self._ensure_downloaded(name, idx, total)
                    with results_lock:
                        download_results[name] = res
                except Exception as exc:  # noqa: BLE001
                    self.log(
                        f"❌ Ошибка фоновой загрузки {name}: {exc}",
                        f"❌ Background download error for {name}: {exc}",
                    )
                    with results_lock:
                        download_results[name] = False
                finally:
                    download_events[name].set()

            if selected_plugins:
                threading.Thread(
                    target=download_task, args=(selected_plugins[0], 0), daemon=True
                ).start()

            for index, plugin_name in enumerate(selected_plugins):
                self.signals.progress_updated.emit(
                    f"({index+1}/{total}) {t.get('wait', 'Ожидание')}: {plugin_name}...",
                    index / total,
                )

                download_events[plugin_name].wait()

                if index + 1 < total:
                    next_plugin = selected_plugins[index + 1]
                    threading.Thread(
                        target=download_task,
                        args=(next_plugin, index + 1),
                        daemon=True,
                    ).start()

                with results_lock:
                    plugin_ok = download_results[plugin_name]

                if not plugin_ok:
                    self.log(
                        f"❌ Пропуск установки {plugin_name} из-за ошибки загрузки.",
                        f"❌ Skipping {plugin_name} installation due to download error.",
                    )
                    continue

                self.signals.progress_updated.emit(
                    f"({index+1}/{total}) {t.get('installing', 'Установка')}: {plugin_name}...",
                    (index + 0.5) / total,
                )
                self.log(
                    f"\n----------------------------------------\n"
                    f"📦 ПЛАГИН: {plugin_name}\n"
                    f"----------------------------------------",
                    f"\n----------------------------------------\n"
                    f"📦 PLUGIN: {plugin_name}\n"
                    f"----------------------------------------",
                )

                if plugin_name in _rg_group:
                    self._rg_run_shared_steps = (plugin_name == _rg_leader)
                else:
                    self._rg_run_shared_steps = True

                self._perform_installation(
                    plugin_name, index, total, ae_version, custom_install_path
                )
                self.signals.progress_updated.emit(
                    f"({index+1}/{total}) {t.get('complete', 'Готово')}: {plugin_name}",
                    (index + 1) / total,
                )

            self.log(
                f"\n{'='*50}\n🔍 ФИНАЛЬНАЯ ПРОВЕРКА...\n{'='*50}",
                f"\n{'='*50}\n🔍 FINAL CHECK...\n{'='*50}",
            )
            for plugin_name in selected_plugins:
                if not self._is_plugin_installed_via_pipeline(plugin_name, ae_version, use_cache=False):
                    self.log(
                        f"❌ [ОШИБКА] Плагин {plugin_name} не найден после установки!",
                        f"❌ [ERROR] Plugin {plugin_name} not found after installation!",
                    )
                else:
                    self.log(
                        f"✅ {plugin_name} прошел проверку.",
                        f"✅ {plugin_name} passed the check.",
                    )

            _maxon_family = {"RedGiant", "Universe", "Trapcode", "MBS"}
            if any(p in _maxon_family for p in selected_plugins):
                warn_ru = t.get(
                    "maxon_activation_warning",
                    "⚠ Если плагины Maxon не работают, попробуйте в "
                    "«Дополнительно» → «Прочее» запустить «Активация Maxon».",
                )
                warn_en = self.lang_dict.get("en", {}).get(
                    "maxon_activation_warning",
                    "⚠ If Maxon plugins don't work, try Advanced → Misc → "
                    "'Run Maxon activation'.",
                )
                self.log(f"\n{warn_ru}", f"\n{warn_en}")

        except Exception as exc:  # noqa: BLE001
            self.log(
                f"\n[КРИТИЧЕСКАЯ ОШИБКА] Общий сбой процесса установки: {exc}",
                f"\n[CRITICAL ERROR] General installation process failure: {exc}",
            )
        finally:
            self.signals.installation_finished.emit(
                t.get("complete", "Complete")
            )

    # ==================================================================
    # start_installation
    # ==================================================================
    def start_installation(self) -> None:
        widget = getattr(self, "install_tab_widget", None)
        if widget is None:
            return

        widget.clear_logs()

        ae_version = self.selected_ae_version or "None"
        if ae_version == "None":
            self.log(
                "[ОШИБКА] Выберите версию After Effects!",
                "[ERROR] Please select an After Effects version!",
            )
            return

        full_ae_version = "20" + ae_version
        force_install = bool(self.force_install)
        selected: list[str] = []

        for name, cb in widget.checkboxes:
            if cb.isChecked():
                if force_install or not self._is_plugin_installed_via_pipeline(name, full_ae_version):
                    selected.append(name)
                else:
                    self.log(
                        f"Пропуск: Плагин {name} уже установлен.",
                        f"Skipped: Plugin {name} is already installed.",
                    )

        if not selected:
            self.log(
                "Нет плагинов для установки или они уже установлены.",
                "No plugins to install or already installed.",
            )
            return

        widget.btn_install.setEnabled(False)
        self.install_in_progress = True
        self.log(
            f"\n{'='*50}\n🚀 УСТАНОВКА AFTER EFFECTS {full_ae_version}\n{'='*50}",
            f"\n{'='*50}\n🚀 INSTALLING AFTER EFFECTS {full_ae_version}\n{'='*50}",
        )

        custom_install_path = (self.custom_install_path or "").strip()
        threading.Thread(
            target=self.run_install_process,
            args=(full_ae_version, selected, custom_install_path),
            daemon=True,
        ).start()

    # ==================================================================
    # Делегаты на pipeline
    # ==================================================================
    def _is_plugin_installed_via_pipeline(
        self, plugin_name: str, ae_version: str, *, use_cache: bool = True
    ) -> bool:
        if ae_version == "None" or not plugin_name:
            return False
        plugin_full = self._lookup_native_plugin_meta(plugin_name)
        if plugin_full is None:
            plugin_full = dict(self.custom_data.get(plugin_name, {}))
            if not plugin_full:
                plugin_full = {"name": plugin_name}

        pipeline = self._get_or_create_pipeline()
        pipeline.update_settings(
            ae_drive=self.ae_drive,
            custom_install_path=(self.custom_install_path or "").strip(),
            options=self._build_options_dict(),
        )

        from plugin_checker import PluginCheckerMixin

        def _legacy(p_name: str, ae_v: str) -> bool:
            return PluginCheckerMixin.is_plugin_installed(self, p_name, ae_v)

        return pipeline.is_plugin_installed(
            plugin_full, ae_version,
            use_cache=use_cache,
            legacy_check=_legacy,
        )

    def is_plugin_installed(self, plugin_name: str, ae_version: str) -> bool:
        return self._is_plugin_installed_via_pipeline(plugin_name, ae_version)

    def uninstall_plugin(self, plugin_name: str, ae_version: str) -> bool:
        from plugin_checker import PluginCheckerMixin

        plugin_full = self._lookup_native_plugin_meta(plugin_name) or dict(
            self.custom_data.get(plugin_name, {}) or {"name": plugin_name}
        )

        if plugin_full.get("uninstall_method") == "control_panel":
            return PluginCheckerMixin.uninstall_plugin(self, plugin_name, ae_version)

        pipeline = self._get_or_create_pipeline()
        pipeline.update_settings(
            ae_drive=self.ae_drive,
            custom_install_path=(self.custom_install_path or "").strip(),
            options=self._build_options_dict(),
        )

        def _legacy(p_name: str, ae_v: str) -> bool:
            return PluginCheckerMixin.uninstall_plugin(self, p_name, ae_v)

        return pipeline.uninstall(plugin_full, ae_version, legacy_uninstall=_legacy)
