import os
import sys
import subprocess
import threading
import webbrowser
import zipfile
import gdown
import customtkinter as ctk
from tkinter import END, messagebox

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
        
        self.check_paths = {
            "RedGiant": lambda ver: [r"C:\Program Files\Maxon", r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\Red Giant"],
            "Sapphire": lambda ver: [
                r"C:\Program Files\GenArts\SapphireAE", 
                r"C:\Program Files\GenArts", 
                r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\GenArts"
            ],
            "Mocha_Pro": lambda ver: [
                r"C:\Program Files\BorisFX\Mocha Pro 2026", 
                r"C:\Program Files\BorisFX\Mocha Pro", 
                r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\BorisFX\MochaPro2026"
            ], 
            "BCC": lambda ver: [
                r"C:\Program Files\BorisFX\ContinuumAE", 
                r"C:\Program Files\BorisFX\Continuum", 
                r"C:\Program Files\BorisFX", 
                r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\BorisFX"
            ],
            "Bokeh": lambda ver: rf"C:\Program Files\Adobe\Adobe After Effects {ver}\Support Files\Plug-ins\Plugins Everything\Bokeh.aex",
            "Deep_Glow": lambda ver: r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\Deep Glow.aex",
            "Deep_Glow2": lambda ver: r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\DeepGlow2.aex",
            "Element": lambda ver: rf"C:\Program Files\Adobe\Adobe After Effects {ver}\Support Files\Plug-ins\VideoCopilot\Element.aex",
            "Fast_Layers": lambda ver: rf"C:\Program Files\Adobe\Adobe After Effects {ver}\Support Files\Scripts\ScriptUI Panels\Fast_Layers.jsx",
            "Flow": lambda ver: r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions\flow",
            "Fxconsole": lambda ver: rf"C:\Program Files\Adobe\Adobe After Effects {ver}\Support Files\Plug-ins\VideoCopilot\FXConsole.aex",
            "Glitchify": lambda ver: rf"C:\Program Files\Adobe\Adobe After Effects {ver}\Support Files\Plug-ins\VideoCopilot\Glitchify.aex",
            "Prime_tool": lambda ver: r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions\com.PrimeTools",
            "RSMB": lambda ver: r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\RSMB",
            "Saber": lambda ver: rf"C:\Program Files\Adobe\Adobe After Effects {ver}\Support Files\Plug-ins\VideoCopilot\Saber.aex",
            "Shake_Generator": lambda ver: rf"C:\Program Files\Adobe\Adobe After Effects {ver}\Support Files\Scripts\ScriptUI Panels\Shake_Generator.jsx",
            "Twich": lambda ver: [rf"C:\Program Files\Adobe\Adobe After Effects {ver}\Support Files\Plug-ins\VideoCopilot\Twitch.aex", rf"C:\Program Files\Adobe\Adobe After Effects {ver}\Support Files\Plug-ins\VideoCopilot\twitch.aex"],
            "Twixtor": lambda ver: r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\Twixtor8AE",
            "textevo2": lambda ver: rf"C:\Program Files\Adobe\Adobe After Effects {ver}\Support Files\Scripts\ScriptUI Panels\TextEvo2.jsxbin",
            "uwu2x": lambda ver: [r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions\uwu2x-pro", r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions\uwu2x"]
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
            "textevo2": "1R6gWidqSVR4HC_c7XB025khxHMLFe_KK",
            "uwu2x": "1X4QYzAAZK0djo0-7a8mn63tpvWNFQs0u"
        }

        self.create_widgets()
        self.version_var.trace_add("write", lambda *args: self.check_installed_plugins())
        
        self.check_installed_plugins()

    def create_widgets(self):
        left_width = 340

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

        # Вывод названия плагина вместе с версией (скрываем 1.0)
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

        self.btn_clear_log = ctk.CTkButton(
            self.right_frame, 
            text="Очистить логи", 
            font=self.font_main, 
            fg_color="#333333", 
            hover_color="#444444", 
            height=30, 
            width=120,
            corner_radius=6,
            command=self.clear_logs
        )
        self.btn_clear_log.pack(anchor="e", pady=(10, 0))

        self.target_y = None
        self._is_animating = False
        self.scrollable_checkbox_frame._mouse_wheel_all = self.smooth_wheel_event

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

    def check_installed_plugins(self):
        ae_ver = self.version_var.get()
        full_ver = "20" + ae_ver if ae_ver != "None" else "None"
        
        for name, var in self.checkboxes:
            check_func = self.check_paths.get(name)
            if check_func:
                paths = check_func(full_ver)
                if isinstance(paths, str):
                    paths = [paths]
                
                is_installed = False
                for path in paths:
                    if "None" not in path and os.path.exists(path):
                        is_installed = True
                        break
                
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
                check_func = self.check_paths.get(name)
                is_installed = False
                if check_func:
                    paths = check_func(full_ae_version)
                    if isinstance(paths, str):
                        paths = [paths]
                    
                    for path in paths:
                        if os.path.exists(path):
                            is_installed = True
                            break
                            
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
                
                target_path_func = self.check_paths.get(plugin_name)
                if target_path_func:
                    paths = target_path_func(ae_version)
                    expected_path = paths[0] if isinstance(paths, list) else paths
                    self.log(f"📂 Целевой путь установки:\n   -> {expected_path}")
                else:
                    self.log(f"📂 Целевой путь определяется системным установщиком.")
                    
                self.log(f"⚙️ Исполняемый файл: {os.path.basename(full_bat_path)}")
                self.log("-" * 40)

                if not os.path.exists(full_bat_path):
                    self.log(f"[ИНФО] Локальные файлы отсутствуют. Начинаем загрузку...")
                    file_id = self.gdrive_file_ids.get(plugin_name)
                    zip_path = os.path.join(self.base_dir, f"{plugin_name}.zip")
                    
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

                if not os.path.exists(full_bat_path):
                    self.log(f"❌ [ОШИБКА] Файл не найден по пути: {full_bat_path}")
                    self.log(f"Проверь структуру скачанного ZIP архива!")
                    continue

                self.log(f"▶ Запуск скрипта установки...")
                cmd = [full_bat_path]
                if needs_version:
                    cmd.append(ae_version)

                try:
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    
                    process = subprocess.Popen(
                        cmd, 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.STDOUT, 
                        stdin=subprocess.DEVNULL, 
                        startupinfo=startupinfo, 
                        shell=True,
                        text=True, 
                        encoding='utf-8', 
                        errors='replace',
                        cwd=self.base_dir
                    )

                    with process.stdout:
                        for line in iter(process.stdout.readline, ''):
                            clean_line = line.strip()
                            if clean_line:
                                self.log(f"   [CMD] {clean_line}")

                    return_code = process.wait()
                    self.log(f"✅ {plugin_name} успешно обработан.")

                except Exception as e:
                    self.log(f"[КРИТ. ОШИБКА] Сбой выполнения {plugin_name}: {str(e)}")

                end_pct = (index + 1) / total
                self.after(0, self._update_progress_ui, f"Завершено: {plugin_name}", end_pct)

            self.log(f"\n{'='*50}")
            self.log("🔍 ФИНАЛЬНАЯ ПРОВЕРКА УСТАНОВКИ...")
            
            failed_plugins = []
            for plugin_name in selected_plugins:
                check_func = self.check_paths.get(plugin_name)
                is_installed = False
                
                if check_func:
                    paths = check_func(ae_version)
                    if isinstance(paths, str):
                        paths = [paths]
                        
                    for path in paths:
                        if os.path.exists(path):
                            is_installed = True
                            break
                
                if not is_installed:
                    failed_plugins.append(plugin_name)
                    self.log(f"❌ [ОШИБКА] Плагин {plugin_name} не найден по ожидаемому пути!")
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

if __name__ == "__main__":
    app = AksiomInstaller()
    app.mainloop()
