import os
import sys
import subprocess
import threading
import webbrowser
import zipfile
import gdown
import customtkinter as ctk
import glob
import urllib.request
import urllib.error
import json
import re
from tkinter import END, messagebox
import shutil
import winreg
import time
import ctypes
import ctypes.wintypes

# =================================================================
# КЛАСС-ПЕРЕХВАТЧИК ДЛЯ ПОЛУЧЕНИЯ ПРОГРЕССА СКАЧИВАНИЯ (tqdm)
# =================================================================
class GdownLogCatcher:
    def __init__(self, ui_app, original_stderr):
        self.ui_app = ui_app
        self.original_stderr = original_stderr
        self.is_progress = False

    def write(self, text):
        if self.original_stderr:
            self.original_stderr.write(text)
            self.original_stderr.flush()

        if not text:
            return

        if '\r' in text:
            clean_text = text.split('\r')[-1].strip()
            if clean_text:
                if not self.is_progress:
                    self.ui_app.after(0, self.ui_app._safe_log, clean_text)
                    self.is_progress = True
                else:
                    self.ui_app.after(0, self.ui_app._update_last_log_line, clean_text)
        else:
            clean_text = text.strip()
            if clean_text:
                if self.is_progress:
                    self.is_progress = False
                self.ui_app.after(0, self.ui_app._safe_log, clean_text)

    def flush(self):
        if self.original_stderr:
            self.original_stderr.flush()

    def isatty(self):
        return True

# Базовые настройки темы
ctk.set_appearance_mode("dark")

class AksiomInstaller(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # ===============================================================
        # ТЕКУЩАЯ ВЕРСИЯ ПРОГРАММЫ (меняйте её при выпуске обновлений)
        self.CURRENT_VERSION = "3,1" 
        # ===============================================================

        self.title("Ae plugins installer")
        self.geometry("820x550")
        self.resizable(False, False)
        
        self.configure(fg_color="#242424")
        
        self.font_main = ("Calibri", 14)
        self.font_title = ("Calibri", 16, "bold")
        self.font_btn = ("Calibri", 18, "bold")

        self.accent_color = "#6658cc"
        self.accent_hover = "#5346a6"

        self.grid_columnconfigure(0, weight=0) 
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
            bundle_dir = sys._MEIPASS
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
            bundle_dir = self.base_dir

        icon_path = os.path.join(bundle_dir, "logo.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        self.plugins_data = [
            ("RedGiant", "2026.3", r"RedGiant\RedGiant.bat", False),
            ("Sapphire", "2026", r"Sapphire\Sapphire.bat", False),
            ("Mocha_Pro", "2026", r"Mocha pro\mochapro_installer.bat", False),
            ("BCC", "2026.0.1", r"BCC\BCC.bat", False),
            ("Bokeh", "1.4.1", r"Bokeh\Bokeh.bat", True),
            ("Deep_Glow", "1.6.6", r"Deep_Glow\Deep_Glow.bat", False),
            ("Deep_Glow2", "1.1", r"Deep_Glow2\deep_glow2.bat", True),
            ("Element", "2.2.3", r"Element\Element.bat", True),
            ("Fast_Layers", "1.0", r"Fast_Layers\Fast_Layers.bat", False),
            ("Flow", "1.5", r"Flow\Flow.bat", False),
            ("Fxconsole", "1.0.5", r"Fxconsole\Fxconsole.bat", True),
            ("Glitchify", "1.0", r"Glitchify\Glitchify.bat", True),
            ("Prime_tool", "1.0", r"Prime_tool\Prime_tool.bat", False),
            ("RSMB", "6.6", r"RSMB\RSMB.bat", False),
            ("Saber", "1.0.40", r"Saber\Saber.bat", True),
            ("Shake_Generator", "1.0", r"Shake_Generator\Shake_Generator.bat", True),
            ("Twich", "1.0.4", r"Twich\Twich.bat", True),
            ("Twixtor", "8.1.0", r"Twixtor\Twixtor.bat", False),
            ("Textevo2", "2.0", r"textevo2\textevo2.bat", True),
            ("Uwu2x", "1.0", r"uwu2x\uwu2x.bat", False)
        ]
        
        self.plugin_keywords = {
            "RedGiant": ["red giant", "maxon"],
            "Sapphire": ["sapphire", "genarts"],
            "Mocha_Pro": ["mocha pro", "mochapro"],
            "BCC": ["continuum", "bcc"],
            "Bokeh": ["bokeh"],
            "Deep_Glow": ["deep glow", "deep_glow", "deepglow.aex"], 
            "Deep_Glow2": ["deepglow2", "deep glow 2", "deep_glow2"],
            "Element": ["element"],
            "Fast_Layers": ["fast_layers", "fast layers"],
            "Flow": ["flow"],
            "Fxconsole": ["fxconsole"],
            "Glitchify": ["glitchify"],
            "Prime_tool": ["primetools", "prime_tool", "com.primetools"],
            "RSMB": ["rsmb"],
            "Saber": ["saber"],
            "Shake_Generator": ["shake_generator", "shake generator"],
            "Twich": ["twitch", "twich"],
            "Twixtor": ["twixtor", "twixtor8ae"],
            "Textevo2": ["textevo2", "textevo"],
            "Uwu2x": ["uwu2x", "uwu2x-pro"]
        }
        
        self.gdrive_file_ids = {
            "RedGiant": "1y8kM4KV6HswkN3L7PqSmLQhy-rL30upC",
            "Sapphire": "1kW-xMFdipm6Q2LsFr5E1_d_IYptF3lvd",
            "Mocha_Pro": "1LrOCjyGIqJH7RfxeO6XqkduweKxp9RMM",
            "BCC": "1XrUp2oNRlu6upIipHg4OelP9xV9Iua7g",
            "Bokeh": "1G-Nq99ZsYglH9VxF4tQ_8B7HKJDcj1fw",
            "Deep_Glow": "1EdJTHsmPwcq2uNFx_SLy9I7_tzeqs0U5",
            "Deep_Glow2": "15u3MNjgbKORw5MeBud7w8jcF_U__BEgT",
            "Element": "1_SredouM2YicE0H3LJ5ZA7A96ICoKrw3", 
            "Fast_Layers": "104Aph7Esk6EbrGBLlWQw5vFO9ducAsfN",
            "Flow": "1ngcSwjjywDGTNQacJiye1Hw_cy_nlsjj",
            "Fxconsole": "1Ta6GJyHN_h87W0g1ciLtr5aX89l_TAYS",
            "Glitchify": "1QbviuYn0E8-Q3_cNT6Rwky7NcrULKRhm",
            "Prime_tool": "1RFDXOHRK_8XbiGHvAz9KGi_THdFF5EKF",
            "RSMB": "1IaEv0f6jk0dE1hu-o5NIDTJ1358w58W5",
            "Saber": "13QCp9VsstYdQgbB00Dq3vpZYP5kuL-nG",
            "Shake_Generator": "10GCJTk-B2bDYMTS0en4wbpq10ceVAFfB",
            "Twich": "1pFZ1DRC3K00uWmRq23Asu-K9dl8Yr9s4",
            "Twixtor": "1Kcjkv4qbqVqaeEYnaeY1vKEkOGioePT9",
            "Textevo2": "1R6gWidqSVR4HC_c7XB025khxHMLFe_KK",
            "Uwu2x": "1X4QYzAAZK0djo0-7a8mn63tpvWNFQs0u"
        }

        self.create_widgets()
        self.version_var.trace_add("write", lambda *args: self.check_installed_plugins())
        
        self.check_installed_plugins()
        self.check_for_updates()

    def create_widgets(self):
        left_width = 340

        # === ЛЕВАЯ ПАНЕЛЬ ===
        self.left_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.left_frame.grid(row=0, column=0, padx=(20, 10), pady=20, sticky="nsew")

        self.lbl_version = ctk.CTkLabel(self.left_frame, text="Выбор версии After Effects", font=self.font_title)
        self.lbl_version.pack(anchor="w", pady=(0, 5))

        self.version_var = ctk.StringVar(value="None")
        versions = ["None", "20", "21", "22", "23", "24", "25"]
        
        self.segmented_button = ctk.CTkSegmentedButton(
            self.left_frame, 
            values=versions, 
            variable=self.version_var,
            font=("Calibri", 12),
            selected_color=self.accent_color,
            selected_hover_color=self.accent_hover,
            unselected_color="#1a1a1a",
            unselected_hover_color="#2a2a2a",
            text_color="#cccccc"
        )
        self.segmented_button.pack(anchor="w", fill="x", pady=(0, 15))

        self.lbl_plugins = ctk.CTkLabel(self.left_frame, text="Выбор плагинов", font=self.font_title)
        self.lbl_plugins.pack(anchor="w", pady=(0, 5))

        self.scrollable_checkbox_frame = ctk.CTkScrollableFrame(
            self.left_frame, 
            width=left_width, 
            height=200, 
            fg_color="#1a1a1a", 
            corner_radius=8
        )
        self.scrollable_checkbox_frame.pack(anchor="w", fill="x", pady=(0, 15))

        self.checkboxes = []
        self.select_all_var = ctk.BooleanVar(value=False)
        
        cb_kwargs = {
            "font": self.font_main,
            "checkbox_width": 18,
            "checkbox_height": 18,
            "border_width": 1,
            "corner_radius": 4,
            "fg_color": self.accent_color,
            "hover_color": self.accent_hover
        }

        self.cb_select_all = ctk.CTkCheckBox(
            self.scrollable_checkbox_frame, 
            text="Выбрать все", 
            variable=self.select_all_var, 
            command=self.toggle_all, 
            **cb_kwargs
        )
        self.cb_select_all.pack(anchor="w", pady=(5, 5), padx=5)

        for plugin_name, version, _, _ in self.plugins_data:
            var = ctk.BooleanVar(value=False)
            
            if version == "1.0":
                display_text = plugin_name
            else:
                display_text = f"{plugin_name}  [v{version}]"
            
            cb = ctk.CTkCheckBox(
                self.scrollable_checkbox_frame, 
                text=display_text, 
                variable=var, 
                command=lambda n=plugin_name, v=var: self.on_plugin_toggle(n, v), 
                **cb_kwargs
            )
            cb.pack(anchor="w", pady=3, padx=5)
            self.checkboxes.append((plugin_name, var))

        self.progress_label = ctk.CTkLabel(self.left_frame, text="Установка: Ожидание...", font=self.font_main, text_color="#aaaaaa")
        self.progress_label.pack(anchor="w", pady=(5, 0))

        self.progressbar = ctk.CTkProgressBar(
            self.left_frame, 
            width=left_width, 
            height=16, 
            progress_color=self.accent_color,
            fg_color="#333333",
            corner_radius=6
        )
        self.progressbar.pack(anchor="w", fill="x", pady=(5, 15)) 
        self.progressbar.set(0)

        self.btn_install = ctk.CTkButton(
            self.left_frame, 
            text="Установка", 
            font=self.font_btn, 
            fg_color=self.accent_color, 
            hover_color=self.accent_hover, 
            height=45, 
            width=left_width,
            corner_radius=8,
            command=self.start_installation
        )
        self.btn_install.pack(anchor="w", fill="x", pady=(0, 10))

        self.footer_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        self.footer_frame.pack(side="bottom", fill="x", pady=(10, 0)) 

        self.btn_github = ctk.CTkButton(
            self.footer_frame, 
            text="GitHub", 
            font=("Calibri", 13, "underline"),
            width=0, 
            height=20,
            fg_color="transparent", 
            text_color="#888888",
            hover_color="#333333",
            command=lambda: webbrowser.open("https://github.com/Aks-iom/Aks-iom-AE-Plugins-install-script")
        )
        self.btn_github.pack(side="left", padx=(0, 10))

        self.btn_telegram = ctk.CTkButton(
            self.footer_frame, 
            text="Telegram", 
            font=("Calibri", 13, "underline"),
            width=0, 
            height=20,
            fg_color="transparent", 
            text_color="#888888",
            hover_color="#333333",
            command=lambda: webbrowser.open("https://t.me/AE_plugins_script")
        )
        self.btn_telegram.pack(side="left", padx=(0, 10))
        
        self.btn_source = ctk.CTkButton(
            self.footer_frame, 
            text="Источник", 
            font=("Calibri", 13, "underline"),
            width=0, 
            height=20,
            fg_color="transparent", 
            text_color="#888888",
            hover_color="#333333",
            command=lambda: webbrowser.open("https://satvrn.li/windows")
        )
        self.btn_source.pack(side="left")

        self.lbl_author = ctk.CTkLabel(
            self.footer_frame, 
            text="By Aksiom", 
            font=("Calibri", 13, "italic"), 
            text_color="#555555"
        )
        self.lbl_author.pack(side="right")

        # === ПРАВАЯ ПАНЕЛЬ ===
        self.right_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.right_frame.grid(row=0, column=1, padx=(10, 20), pady=20, sticky="nsew")

        self.lbl_log = ctk.CTkLabel(self.right_frame, text="Журнал событий", font=self.font_title)
        self.lbl_log.pack(anchor="w", pady=(0, 5))

        self.log_textbox = ctk.CTkTextbox(
            self.right_frame, 
            font=("Consolas", 12), 
            fg_color="#151515", 
            text_color="#cccccc",
            border_width=1,
            border_color="#333333",
            corner_radius=8
        )
        self.log_textbox.pack(fill="both", expand=True)
        self.log_textbox.configure(state="disabled")

        # Контейнер для кнопок "Обновление" и "Очистить логи"
        self.right_bottom_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.right_bottom_frame.pack(fill="x", pady=(10, 0))

        self.btn_clear_log = ctk.CTkButton(
            self.right_bottom_frame, 
            text="Очистить логи", 
            font=self.font_main, 
            fg_color="#333333", 
            hover_color="#444444", 
            height=30, 
            width=120,
            corner_radius=6,
            command=self.clear_logs
        )
        self.btn_clear_log.pack(side="right")

        self.target_y = None
        self._is_animating = False
        self.scrollable_checkbox_frame._mouse_wheel_all = self.smooth_wheel_event
        
    def extract_version_number(self, text):
        text = text.replace(',', '.')
        match = re.search(r'\d+(\.\d+)*', text)
        if match:
            return match.group()
        return "0.0"

    def extract_display_version(self, text):
        match = re.search(r'(?:Beta\s*)?\d+(?:[.,]\d+)*', text, re.IGNORECASE)
        if match:
            found = match.group()
            if found.lower().startswith('beta'):
                return "V.Beta " + found[4:].strip()
            else:
                return "V." + found
        return text

    def is_version_newer(self, latest, current):
        v_latest = tuple(map(int, self.extract_version_number(latest).split('.')))
        v_current = tuple(map(int, self.extract_version_number(current).split('.')))
        
        length = max(len(v_latest), len(v_current))
        v_latest += (0,) * (length - len(v_latest))
        v_current += (0,) * (length - len(v_current))
        
        return v_latest > v_current

    def check_for_updates(self):
        def fetch():
            try:
                self.after(0, lambda: self.log("[ОБНОВЛЕНИЕ] Подключение к серверам GitHub..."))
                url = "https://api.github.com/repos/Aks-iom/Aks-iom-AE-Plugins-install-script/releases/tags/AE"
                req = urllib.request.Request(url, headers={'User-Agent': 'AksiomInstaller'})
                
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode())
                    release_name = data.get("name", "")
                    
                    if self.is_version_newer(release_name, self.CURRENT_VERSION):
                        display_version = self.extract_display_version(release_name)
                        self.after(0, lambda: self.show_update_button(display_version))
                        self.after(0, lambda: self.log(f"[ОБНОВЛЕНИЕ] Найдена новая версия: {display_version}"))
                    else:
                        self.after(0, lambda: self.log("[ОБНОВЛЕНИЕ] У вас установлена актуальная версия."))
                        
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    self.after(0, lambda: self.log("⚠️ [ОБНОВЛЕНИЕ] Ошибка 403: Превышен лимит запросов GitHub (60 проверок в час). Попробуйте позже."))
                elif e.code == 404:
                    self.after(0, lambda: self.log("⚠️ [ОБНОВЛЕНИЕ] Ошибка 404: Релиз с тегом 'AE' не найден на GitHub."))
                else:
                    self.after(0, lambda: self.log(f"⚠️ [ОБНОВЛЕНИЕ] Ошибка сервера: {e.code}"))
            except Exception as e:
                self.after(0, lambda: self.log(f"⚠️ [ОБНОВЛЕНИЕ] Ошибка сети при проверке: {e}"))

        threading.Thread(target=fetch, daemon=True).start()

    def show_update_button(self, release_title):
        self.btn_update = ctk.CTkButton(
            self.right_bottom_frame,
            text=f"Скачать обновление ({release_title})",
            font=self.font_main, 
            fg_color=self.accent_color, 
            hover_color=self.accent_hover,
            height=30,
            corner_radius=6,
            command=lambda: webbrowser.open("https://github.com/Aks-iom/Aks-iom-AE-Plugins-install-script/releases/tag/AE")
        )
        self.btn_update.pack(side="left", fill="x", expand=True, padx=(0, 10))

    def smooth_wheel_event(self, event):
        if not self.scrollable_checkbox_frame._check_if_mouse_inside(event.x_root, event.y_root):
            return
            
        canvas = self.scrollable_checkbox_frame._parent_canvas
        top, bottom = canvas.yview()
        if top == 0.0 and bottom == 1.0:
            return

        direction = -1 if event.delta > 0 else 1
        step = 0.06 
        
        if self.target_y is None:
            self.target_y = top
            
        self.target_y += direction * step
        self.target_y = max(0.0, min(1.0, self.target_y))
        
        if not self._is_animating:
            self._is_animating = True
            self.animate_scroll(canvas)

    def animate_scroll(self, canvas):
        current_y = canvas.yview()[0]
        if self.target_y is not None:
            diff = self.target_y - current_y
            if abs(diff) > 0.001:
                new_y = current_y + diff * 0.25 
                canvas.yview_moveto(new_y)
                self.after(16, self.animate_scroll, canvas)
            else:
                canvas.yview_moveto(self.target_y)
                self.target_y = None
                self._is_animating = False

    def is_plugin_installed(self, plugin_name, ae_version):
        search_dirs = [
            r"C:\Program Files\BorisFX",
            r"C:\Program Files\BorisFX\ContinuumAE\14\lib",
            r"C:\Program Files\Adobe",
            r"C:\Program Files\Maxon",
            r"C:\Program Files\GenArts",
            rf"C:\Program Files\Adobe\Adobe After Effects {ae_version}\Support Files\Plug-ins\Plugins Everything",
            rf"C:\Program Files\Adobe\Adobe After Effects {ae_version}\Support Files\Plug-ins\VideoCopilot",
            r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore",
            r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\RSMB",
            r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\Twixtor8AE",
            r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions",
            r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions\flow",
            r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions\com.PrimeTools",
            r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions\uwu2x-pro",
            r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions\uwu2x",
            r"C:\ProgramData",
            r"C:\ProgramData\VideoCopilot",
            r"C:\ProgramData\GenArts\rlm"
        ]
        
        script_panels = glob.glob(r"C:\Program Files\Adobe\Adobe After Effects*\Support Files\Scripts\ScriptUI Panels")
        search_dirs.extend(script_panels)
        
        valid_dirs = list(set(d for d in search_dirs if os.path.exists(d)))
        keywords = self.plugin_keywords.get(plugin_name, [plugin_name.lower()])
        
        for d in valid_dirs:
            try:
                for item in os.listdir(d):
                    item_lower = item.lower()
                    for kw in keywords:
                        if kw.lower() in item_lower:
                            if plugin_name == "Deep_Glow" and "2" in item_lower and "deep" in item_lower:
                                continue
                            return True
                            
                dir_name_lower = os.path.basename(d).lower()
                for kw in keywords:
                    if kw.lower() in dir_name_lower:
                        if plugin_name == "Deep_Glow" and "2" in dir_name_lower and "deep" in dir_name_lower:
                            continue
                        return True
                        
            except Exception:
                pass
                
        if plugin_name == "Sapphire":
            if glob.glob(r"C:\ProgramData\GenArts\rlm\*.lic"):
                return True
                
        return False

    def check_installed_plugins(self):
        ae_ver = self.version_var.get()
        full_ver = "20" + ae_ver if ae_ver != "None" else "None"
        
        for name, var in self.checkboxes:
            is_installed = False
            if full_ver != "None":
                is_installed = self.is_plugin_installed(name, full_ver)
            
            for child in self.scrollable_checkbox_frame.winfo_children():
                if isinstance(child, ctk.CTkCheckBox) and child.cget("text").startswith(name):
                    if is_installed:
                        child.configure(text_color="#4CAF50") 
                    else:
                        child.configure(text_color="#cccccc") 

    def toggle_all(self):
        state = self.select_all_var.get()
        for _, var in self.checkboxes:
            var.set(state)
            
        if state:
            self.log("\n⚠️ Внимание (RedGiant):\n( К сожалению установщик плагинов maxon очень не стабилен поэтому с ним могут возникнуть проблемы )")

    def on_plugin_toggle(self, plugin_name, var):
        self.check_individual_state()
        if plugin_name == "RedGiant" and var.get():
            self.log("\n⚠️ Внимание (RedGiant):\n( К сожалению установщик плагинов maxon очень не стабилен поэтому с ним могут возникнуть проблемы )")

    def check_individual_state(self):
        all_checked = all(var.get() for _, var in self.checkboxes)
        self.select_all_var.set(all_checked)

    def log(self, message):
        self.after(0, self._safe_log, message)

    def _safe_log(self, message):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def _update_last_log_line(self, message):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("end-2c linestart", "end-1c")
        self.log_textbox.insert("end-1c", message)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def _update_progress_ui(self, text, value):
        self.progress_label.configure(text=text)
        self.progressbar.set(value)

    def _finish_installation_ui(self):
        self.progress_label.configure(text="Установка: Завершена")
        self.progressbar.set(1.0)
        try:
            self.check_installed_plugins() 
        except Exception as e:
            self._safe_log(f"[ОШИБКА UI] {e}")
        self.btn_install.configure(state="normal")

    def clear_logs(self):
        self.log_textbox.configure(state="normal") 
        self.log_textbox.delete("1.0", "end")        
        self.log_textbox.configure(state="disabled") 

    def download_from_gdrive(self, file_id, destination_path):
        if not file_id or file_id == "ВСТАВЬТЕ_ID_СЮДА":
            self.log(f"[ОШИБКА] Не указан Google Drive ID для скачивания.")
            return False
            
        original_stderr = sys.stderr
        try:
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            self.log(f"[*] Загрузка архива с Google Диска...")
            
            sys.stderr = GdownLogCatcher(self, original_stderr)
            output = gdown.download(id=file_id, output=destination_path, quiet=False)
            sys.stderr = original_stderr
            
            if output:
                self.log(f"[+] Архив скачан.")
                return True
            else:
                self.log(f"[ОШИБКА] Не удалось скачать файл. Проверьте ID или права доступа.")
                return False
        except Exception as e:
            sys.stderr = original_stderr
            self.log(f"[ОШИБКА] Критическая ошибка при скачивании: {e}")
            return False

    def start_installation(self):
        self.clear_logs()

        ae_version = self.version_var.get()
        if ae_version != "None":
            full_ae_version = "20" + ae_version
        else:
            self.log("[ОШИБКА] Пожалуйста, выберите версию After Effects!")
            return

        ae_folder_path = rf"C:\Program Files\Adobe\Adobe After Effects {full_ae_version}"
        if not os.path.exists(ae_folder_path):
            messagebox.showerror(
                "Ошибка: After Effects не найден", 
                f"Не удалось найти After Effects {full_ae_version}!\n\nОжидаемый путь:\n{ae_folder_path}\n\nПожалуйста, убедитесь, что программа установлена правильно."
            )
            return

        selected_plugins = []
        skipped_plugins = []

        for name, var in self.checkboxes:
            if var.get(): 
                is_installed = self.is_plugin_installed(name, full_ae_version)
                            
                if is_installed:
                    skipped_plugins.append(name)
                    var.set(False) 
                else:
                    selected_plugins.append(name)

        if skipped_plugins:
            self.log(f"[ОТМЕНА] Следующие плагины уже установлены и были пропущены:")
            self.log(f"   -> {', '.join(skipped_plugins)}")

        if not selected_plugins:
            self.log("\n[ИНФО] Нет плагинов для установки. Выберите неустановленные плагины.")
            return

        self.btn_install.configure(state="disabled")
        self.log(f"\n{'='*50}")
        self.log(f"🚀 НАЧАЛО УСТАНОВКИ ДЛЯ AFTER EFFECTS {full_ae_version}")
        self.log(f"{'='*50}")
        
        threading.Thread(target=self.run_install_process, args=(full_ae_version, selected_plugins), daemon=True).start()
    def execute_native_install(self, plugin_name, ae_version, src_dir):
        """Выполняет установку плагина средствами Python без использования .bat"""
        import zipfile
        
        if plugin_name == "BCC":
            setup_exe = os.path.join(src_dir, "BCC_Setup.exe")
            subprocess.run([setup_exe, "/s", "/v/qb", "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True)
            bcc_lib = r"C:\Program Files\BorisFX\ContinuumAE\14\lib"
            os.makedirs(bcc_lib, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Crack", "Continuum_Common_AE.dll"), bcc_lib)
            prog_data_rlm = r"C:\ProgramData\GenArts\rlm"
            if os.path.exists(prog_data_rlm):
                for lic in glob.glob(os.path.join(prog_data_rlm, "*.lic")):
                    try: os.remove(lic)
                    except: pass
            shutil.copytree(os.path.join(src_dir, "Crack", "GenArts"), r"C:\ProgramData\GenArts", dirs_exist_ok=True)

        elif plugin_name == "Bokeh":
            dest = rf"C:\Program Files\Adobe\Adobe After Effects {ae_version}\Support Files\Plug-ins\Plugins Everything"
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Bokeh.aex"), dest)

        elif plugin_name == "Deep_Glow":
            dest = r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore"
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Deep Glow.aex"), dest)

        elif plugin_name == "Deep_Glow2":
            dest = r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore"
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "DeepGlow2.aex"), dest)
            shutil.copy2(os.path.join(src_dir, "IrisBlurSDK.dll"), dest)

        elif plugin_name == "Element":
            dest_plugin = rf"C:\Program Files\Adobe\Adobe After Effects {ae_version}\Support Files\Plug-ins\VideoCopilot"
            dest_lic = r"C:\ProgramData\VideoCopilot"
            
            # Получаем реальный путь к "Моим документам" через API Windows
            CSIDL_PERSONAL = 5 
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, 0, buf)
            real_documents_path = buf.value

            dest_docs = os.path.join(real_documents_path, "VideoCopilot")
            
            os.makedirs(dest_plugin, exist_ok=True)
            os.makedirs(dest_lic, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Element.aex"), dest_plugin)
            shutil.copy2(os.path.join(src_dir, "element2_license"), dest_lic)
            shutil.copytree(os.path.join(src_dir, "VideoCopilot"), dest_docs, dirs_exist_ok=True)

        elif plugin_name == "Fast_Layers":
            ae_base = r"C:\Program Files\Adobe"
            if os.path.exists(ae_base):
                for d in glob.glob(os.path.join(ae_base, "Adobe After Effects*")):
                    scripts_path = os.path.join(d, "Support Files", "Scripts", "ScriptUI Panels")
                    if os.path.exists(os.path.join(d, "Support Files", "Scripts")):
                        os.makedirs(scripts_path, exist_ok=True)
                        shutil.copy2(os.path.join(src_dir, "Fast_Layers.jsx"), scripts_path)

        elif plugin_name == "Flow":
            dest = r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions\flow"
            src_flow = os.path.join(src_dir, "flow-v1.5.2")
            if os.path.exists(src_flow):
                shutil.copytree(src_flow, dest, dirs_exist_ok=True)
            for csxs in ["CSXS.10", "CSXS.11", "CSXS.12"]:
                try:
                    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Adobe\{csxs}")
                    winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
                    winreg.CloseKey(key)
                except Exception as e:
                    self.log(f"   [ОШИБКА РЕЕСТРА] Не удалось добавить ключ {csxs}: {e}")

        elif plugin_name == "Fxconsole":
            dest = rf"C:\Program Files\Adobe\Adobe After Effects {ae_version}\Support Files\Plug-ins\VideoCopilot"
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "FXConsole.aex"), dest)

        elif plugin_name == "Glitchify":
            dest = rf"C:\Program Files\Adobe\Adobe After Effects {ae_version}\Support Files\Plug-ins\VideoCopilot"
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Glitchify.aex"), dest)

        elif plugin_name == "Mocha_Pro":
            installer_path = os.path.join(src_dir, "mochapro_2026.0.1_adobe_installer.exe")
            subprocess.run([installer_path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True)
            time.sleep(4)
            subprocess.run(["taskkill", "/F", "/IM", "mochapro.exe", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["taskkill", "/F", "/IM", "mocha.exe", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        elif plugin_name == "RSMB":
            dest = r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\RSMB"
            os.makedirs(dest, exist_ok=True)
            for aex in glob.glob(os.path.join(src_dir, "*.aex")):
                shutil.copy2(aex, dest)

        elif plugin_name == "Saber":
            dest = rf"C:\Program Files\Adobe\Adobe After Effects {ae_version}\Support Files\Plug-ins\VideoCopilot"
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Saber.aex"), dest)

        elif plugin_name == "Sapphire":
            installer_path = os.path.join(src_dir, "sapphire_ae_install.exe")
            try:
                subprocess.run([installer_path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True)
            except subprocess.CalledProcessError as e:
                if e.returncode == 3010:
                    self.log("   [ИНФО] Установка завершена (требуется перезагрузка ПК в будущем)")
                else:
                    raise e

        elif plugin_name == "Shake_Generator":
            dest = rf"C:\Program Files\Adobe\Adobe After Effects {ae_version}\Support Files\Scripts\ScriptUI Panels"
            os.makedirs(dest, exist_ok=True)
            for jsx in glob.glob(os.path.join(src_dir, "*.jsx")):
                shutil.copy2(jsx, dest)

        elif plugin_name == "Textevo2":
            dest = rf"C:\Program Files\Adobe\Adobe After Effects {ae_version}\Support Files\Scripts\ScriptUI Panels"
            os.makedirs(dest, exist_ok=True)
            for jsxbin in glob.glob(os.path.join(src_dir, "*.jsxbin")):
                shutil.copy2(jsxbin, dest)

        elif plugin_name == "Twich":
            dest = rf"C:\Program Files\Adobe\Adobe After Effects {ae_version}\Support Files\Plug-ins\VideoCopilot"
            os.makedirs(dest, exist_ok=True)
            for aex in glob.glob(os.path.join(src_dir, "*.aex")):
                shutil.copy2(aex, dest)
            for key_file in glob.glob(os.path.join(src_dir, "*.key")):
                shutil.copy2(key_file, dest)

        elif plugin_name == "Twixtor":
            dest = r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\Twixtor8AE"
            os.makedirs(dest, exist_ok=True)
            src_twixtor = os.path.join(src_dir, "Twixtor8AE")
            if os.path.exists(src_twixtor):
                shutil.copytree(src_twixtor, dest, dirs_exist_ok=True)

        elif plugin_name == "Uwu2x":
            cep_path = r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions"
            os.makedirs(cep_path, exist_ok=True)
            src_pro = os.path.join(src_dir, "uwu2x-pro")
            src_norm = os.path.join(src_dir, "uwu2x")
            
            if os.path.exists(src_pro):
                shutil.copytree(src_pro, os.path.join(cep_path, "uwu2x-pro"), dirs_exist_ok=True)
            elif os.path.exists(src_norm):
                shutil.copytree(src_norm, os.path.join(cep_path, "uwu2x"), dirs_exist_ok=True)
            
            for i in range(10, 17):
                try:
                    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Adobe\CSXS.{i}")
                    winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
                    winreg.CloseKey(key)
                except Exception as e:
                    self.log(f"   [ОШИБКА РЕЕСТРА] {e}")

        elif plugin_name == "Prime_tool":
            cep_path = r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions\com.PrimeTools"
            zxp_file = os.path.join(src_dir, "com.PrimeTools.cep.zxp")
            if os.path.exists(zxp_file):
                with zipfile.ZipFile(zxp_file, 'r') as zip_ref:
                    zip_ref.extractall(cep_path)

        elif plugin_name == "RedGiant":
            subprocess.run([os.path.join(src_dir, "1_Maxon.exe"), "--mode", "unattended", "--unattendedmodeui", "minimal"], check=True)
            subprocess.run([os.path.join(src_dir, "2_RedGiant.exe"), "--mode", "unattended", "--unattendedmodeui", "minimal"], check=True)
            subprocess.run([os.path.join(src_dir, "3_Unlocker.exe"), "/SILENT"], check=True)
            time.sleep(6)
            subprocess.run(["taskkill", "/F", "/IM", "Maxon App.exe", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["taskkill", "/F", "/IM", "Maxon.exe", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def run_install_process(self, ae_version, selected_plugins):
        try:
            total = len(selected_plugins)
            
            for index, plugin_name in enumerate(selected_plugins):
                plugin_info = next((p for p in self.plugins_data if p[0] == plugin_name), None)
                if not plugin_info:
                    continue

                _, _, bat_path, needs_version = plugin_info
                full_bat_path = os.path.join(self.base_dir, bat_path)

                start_pct = index / total
                self.after(0, self._update_progress_ui, f"Установка: {plugin_name}...", start_pct)
                
                self.log(f"\n" + "-"*40)
                self.log(f"📦 ПЛАГИН: {plugin_name}")
                self.log(f"📂 Целевой путь определяется автоматически по ключевым словам.")
                self.log(f"⚙️ Исполняемый файл: {os.path.basename(full_bat_path)}")
                self.log("-" * 40)

                plugin_src_dir = os.path.dirname(full_bat_path)
                
                # Обязательно нужно определить куда скачивать архив
                zip_path = os.path.join(self.base_dir, f"{plugin_name}.zip")
                
                if not os.path.exists(plugin_src_dir):
                    self.log(f"[ИНФО] Локальная папка плагина отсутствует. Начинаем загрузку...")
                    file_id = self.gdrive_file_ids.get(plugin_name)
                    
                    success = self.download_from_gdrive(file_id, zip_path)
                    if not success:
                        self.log(f"[ПРОПУСК] Установка {plugin_name} отменена.")
                        continue

                    self.log(f"[*] Извлечение файлов из архива...")
                    try:
                        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                            zip_ref.extractall(self.base_dir)
                        self.log(f"[+] Распаковка успешно завершена.")
                        os.remove(zip_path)
                    except zipfile.BadZipFile:
                        self.log(f"[ОШИБКА] Скачанный файл поврежден.")
                        continue
                    except Exception as e:
                        self.log(f"[ОШИБКА] Ошибка извлечения: {e}")
                        continue

                native_plugins = [
                    "RedGiant", "Sapphire", "Mocha_Pro", "BCC", "Bokeh", "Deep_Glow", 
                    "Deep_Glow2", "Element", "Fast_Layers", "Flow", "Fxconsole", 
                    "Glitchify", "Prime_tool", "RSMB", "Saber", "Shake_Generator", 
                    "Twich", "Twixtor", "Textevo2", "Uwu2x"
                ]

                try:
                    if plugin_name in native_plugins:
                        self.log(f"▶ Выполнение встроенной установки (native Python)...")
                        plugin_src_dir = os.path.dirname(full_bat_path)
                        self.execute_native_install(plugin_name, ae_version, plugin_src_dir)
                        self.log(f"✅ {plugin_name} успешно установлен.")
                    else:
                        self.log(f"❌ [ОШИБКА] Плагин {plugin_name} не поддерживается нативным установщиком.")
                
                except Exception as e:
                    self.log(f"❌ [КРИТ. ОШИБКА] Сбой выполнения {plugin_name}: {str(e)}")

                end_pct = (index + 1) / total
                self.after(0, self._update_progress_ui, f"Завершено: {plugin_name}", end_pct)

            self.log(f"\n{'='*50}")
            self.log("🔍 ФИНАЛЬНАЯ ПРОВЕРКА УСТАНОВКИ...")
            
            failed_plugins = []
            for plugin_name in selected_plugins:
                is_installed = self.is_plugin_installed(plugin_name, ae_version)
                
                if not is_installed:
                    failed_plugins.append(plugin_name)
                    self.log(f"❌ [ОШИБКА] Плагин {plugin_name} не найден после установки!")
                else:
                    self.log(f"✅ {plugin_name} корректно установлен.")

            self.log(f"\n{'='*50}")
            if failed_plugins:
                self.log("⚠️ Установка завершена, но следующие плагины НЕ НАЙДЕНЫ:")
                for fp in failed_plugins:
                    self.log(f"   -> {fp}")
                self.log("(Возможно, установщик отработал с ошибкой или установил файлы в нестандартную директорию)")
            else:
                self.log("🎉 ВСЕ ВЫБРАННЫЕ ПЛАГИНЫ УСПЕШНО УСТАНОВЛЕНЫ И НАЙДЕНЫ!")
                
            self.log("\nЕсли возникли проблемы или предложения просьба написать Not_aks.t.me")
            self.log(f"{'='*50}")

        except Exception as e:
            self.log(f"\n[КРИТИЧЕСКАЯ ОШИБКА ПРОГРАММЫ] Сбой в фоновом потоке: {e}")
        
        finally:
            self.after(0, self._finish_installation_ui)

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if __name__ == "__main__":
    if is_admin():
        app = AksiomInstaller()
        app.mainloop()
    else:
        # Правильный перезапуск с учетом пробелов в путях и формата запуска (exe или py)
        if getattr(sys, 'frozen', False):
            # Для скомпилированного .exe
            params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
        else:
            # Для запуска через исходник .py
            params = f'"{os.path.abspath(__file__)}" ' + " ".join([f'"{arg}"' for arg in sys.argv[1:]])

        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        sys.exit() # Обязательно завершаем текущий процесс без прав