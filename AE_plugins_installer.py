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
import locale
from tkinter import END, messagebox, filedialog
import shutil
import winreg
import time
import ctypes
import ctypes.wintypes
import hashlib
import io

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding='utf-8')
if isinstance(sys.stderr, io.TextIOWrapper):
    sys.stderr.reconfigure(encoding='utf-8')

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

ctk.set_appearance_mode("dark")

class GdownLogCatcher:
    def __init__(self, ui_app, original_stderr, current_index, total_plugins, plugin_name):
        self.ui_app = ui_app
        self.original_stderr = original_stderr
        self.current_index = current_index
        self.total_plugins = total_plugins
        self.plugin_name = plugin_name
        self.last_percent = -1

    def write(self, text):
        if self.original_stderr:
            self.original_stderr.write(text)
            self.original_stderr.flush()

        if not text: return

        if '%' in text:
            match = re.search(r'(\d+)%', text)
            if match:
                percent = int(match.group(1))
                if percent != self.last_percent and (percent % 5 == 0 or percent == 100):
                    self.last_percent = percent
                    self.ui_app._update_last_log_line(
                        f"Загрузка {self.plugin_name}: {percent}%",
                        f"Downloading {self.plugin_name}: {percent}%"
                    )
                    
                    base_prog = self.current_index / self.total_plugins
                    chunk_prog = (percent / 100) * (1 / self.total_plugins)
                    self.ui_app.after(0, self.ui_app.progressbar.set, base_prog + chunk_prog)

    def flush(self):
        if self.original_stderr:
            self.original_stderr.flush()

class AdvancedFrame(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        
        self.sidebar_frame = ctk.CTkFrame(self, width=180, corner_radius=0, fg_color="#1a1a1a")
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)

        self.btn_tab_changelog = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_changelog", "Changelog"), font=self.app.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_changelog
        )
        self.btn_tab_changelog.pack(pady=(20, 5), padx=10, fill="x")

        self.btn_tab_logs = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_logs", "Logs"), font=self.app.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_logs
        )
        self.btn_tab_logs.pack(pady=5, padx=10, fill="x")

        self.btn_tab_custom = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_custom", "Custom Plugins"), font=self.app.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_custom
        )
        self.btn_tab_custom.pack(pady=5, padx=10, fill="x")

        self.btn_tab_settings = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_settings", "Individual Paths"), font=self.app.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_settings
        )
        self.btn_tab_settings.pack(pady=5, padx=10, fill="x")
        
        self.btn_tab_sync = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_sync", "Export / Import"), font=self.app.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_sync
        )
        self.btn_tab_sync.pack(pady=5, padx=10, fill="x")

        self.btn_tab_uninstall = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_uninstall", "Uninstall Plugins"), font=self.app.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_uninstall
        )
        self.btn_tab_uninstall.pack(pady=5, padx=10, fill="x")

        self.btn_tab_options = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_options", "Прочее"), font=self.app.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_options
        )
        self.btn_tab_options.pack(pady=5, padx=10, fill="x")

        self.frame_changelog = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_logs = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_custom = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_settings = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_sync = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_uninstall = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_options = ctk.CTkFrame(self, fg_color="transparent")

        self.changelog_text = ctk.CTkTextbox(
            self.frame_changelog, font=("Calibri", 14), fg_color="#151515", 
            text_color="#bbbbbb", wrap="word", corner_radius=8
        )
        self.changelog_text.pack(fill="both", expand=True, padx=20, pady=20)
        self.changelog_text.insert("1.0", self.app.CHANGELOG_TEXT[self.app.current_lang])
        self.changelog_text.configure(state="disabled")

        self.log_textbox = ctk.CTkTextbox(
            self.frame_logs, font=("Consolas", 12), fg_color="#151515", 
            text_color="#cccccc", wrap="word", corner_radius=8
        )
        self.log_textbox.pack(fill="both", expand=True, padx=20, pady=(20, 10))
        
        self.btn_export = ctk.CTkButton(
            self.frame_logs, text=t.get("export_log_btn", "Export Logs"), font=self.app.font_main, 
            fg_color="#333333", hover_color="#444444", height=35, corner_radius=6, 
            command=self.export_persistent_logs
        )
        self.btn_export.pack(side="right", padx=20, pady=(0, 20))

        self.frame_settings.grid_columnconfigure(0, weight=1)
        self.frame_settings.grid_rowconfigure(1, weight=1) 
        
        self.lbl_settings_title = ctk.CTkLabel(self.frame_settings, text=t.get("settings_title", "Individual Paths"), font=self.app.font_title)
        self.lbl_settings_title.grid(row=0, column=0, pady=(30, 20))

        self.btn_reset_all = ctk.CTkButton(
            self.frame_settings, text=t.get("reset_all", "Reset All"), font=("Calibri", 12, "bold"),
            width=100, height=28, fg_color="#552222", hover_color="#772222",
            command=self.reset_all_paths
        )
        self.btn_reset_all.grid(row=0, column=0, sticky="e", padx=20, pady=(30, 20))

        self.settings_scroll = ctk.CTkScrollableFrame(self.frame_settings, fg_color="transparent")
        self.settings_scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))

        self.path_entries = {}
        self.after(200, self.build_settings_ui)

        self.sync_wrapper = ctk.CTkFrame(self.frame_sync, fg_color="transparent")
        self.sync_wrapper.pack(expand=True, anchor="center", pady=20)

        self.lbl_sync_title = ctk.CTkLabel(self.sync_wrapper, text=t.get("sync_title", "Data Management"), font=self.app.font_title)
        self.lbl_sync_title.pack(pady=(0, 25))

        self.card_paths = ctk.CTkFrame(self.sync_wrapper, fg_color="#1a1a1a", corner_radius=8, width=460)
        self.card_paths.pack(fill="x", pady=(0, 15))
        
        self.lbl_sync_paths = ctk.CTkLabel(self.card_paths, text=t.get("sync_paths", "Custom Installation Paths"), font=("Calibri", 14, "bold"), text_color="#cccccc")
        self.lbl_sync_paths.pack(pady=(15, 10))

        btn_frame_paths = ctk.CTkFrame(self.card_paths, fg_color="transparent")
        btn_frame_paths.pack(fill="x", padx=20, pady=(0, 20))
        
        self.btn_export_paths = ctk.CTkButton(
            btn_frame_paths, text=t.get("export_btn", "Export"), font=("Calibri", 14, "bold"), 
            fg_color="#333333", hover_color="#444444", height=35, command=self.export_paths
        )
        self.btn_export_paths.pack(side="left", expand=True, fill="x", padx=(0, 5))

        self.btn_import_paths = ctk.CTkButton(
            btn_frame_paths, text=t.get("import_btn", "Import"), font=("Calibri", 14, "bold"), 
            fg_color=self.app.accent_color, hover_color=self.app.accent_hover, height=35, command=self.import_paths
        )
        self.btn_import_paths.pack(side="right", expand=True, fill="x", padx=(5, 0))

        self.card_plugins = ctk.CTkFrame(self.sync_wrapper, fg_color="#1a1a1a", corner_radius=8, width=460)
        self.card_plugins.pack(fill="x", pady=(0, 25))

        self.lbl_sync_custom = ctk.CTkLabel(self.card_plugins, text=t.get("sync_custom", "Custom Plugins"), font=("Calibri", 14, "bold"), text_color="#cccccc")
        self.lbl_sync_custom.pack(pady=(15, 10))

        self.lbl_sync_warn = ctk.CTkLabel(self.sync_wrapper, text=t.get("sync_warn", "Note: Local files are not transferred."), font=("Calibri", 12), text_color="#888888", justify="center")
        self.lbl_sync_warn.pack(pady=(0, 0))

        self.frame_uninstall.grid_columnconfigure(0, weight=1)
        self.frame_uninstall.grid_rowconfigure(3, weight=1)

        self.lbl_un_title = ctk.CTkLabel(self.frame_uninstall, text=t.get("un_title", "Uninstall Plugins"), font=self.app.font_title)
        self.lbl_un_title.grid(row=0, column=0, pady=(30, 5))
        
        self.lbl_un_desc = ctk.CTkLabel(self.frame_uninstall, text=t.get("un_desc", "Showing plugins installed for selected AE version."), font=("Calibri", 12), text_color="#aaaaaa")
        self.lbl_un_desc.grid(row=1, column=0, pady=(0, 15))

        self.un_version_var = ctk.StringVar(value=self.app.version_var.get())
        versions = ["None", "20", "21", "22", "23", "24", "25" , "26"]
        self.un_version_seg = ctk.CTkSegmentedButton(
            self.frame_uninstall, values=versions, variable=self.un_version_var,
            font=("Calibri", 12), selected_color=self.app.accent_color,
            selected_hover_color=self.app.accent_hover, unselected_color="#1a1a1a", text_color="#cccccc"
        )
        self.un_version_seg.grid(row=2, column=0, pady=(0, 15), padx=20, sticky="ew")
        self.un_version_var.trace_add("write", lambda *args: self.build_uninstall_ui())

        self.uninstall_scroll = ctk.CTkScrollableFrame(self.frame_uninstall, fg_color="transparent")
        self.uninstall_scroll.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 20))

        # Прочее (Добавленная вкладка)
        self.lbl_options_title = ctk.CTkLabel(self.frame_options, text=t.get("options_title", "Прочие настройки"), font=self.app.font_title)
        self.lbl_options_title.pack(anchor="w", pady=(30, 10), padx=20)

        self.cb_old_rsmb = ctk.CTkCheckBox(
            self.frame_options, text=t.get("old_rsmb_lbl", "Старый установщик RSMB"),
            variable=self.app.old_rsmb_var, font=self.app.font_main,
            fg_color=self.app.accent_color, hover_color=self.app.accent_hover
        )
        self.cb_old_rsmb.pack(anchor="w", pady=10, padx=20)

        self.cb_rg_plugin_only = ctk.CTkCheckBox(
            self.frame_options, text=t.get("rg_plugin_only_lbl", "Установка и активация плагинов (RedGiant/Universe)"),
            variable=self.app.rg_plugin_only_var, font=self.app.font_main,
            fg_color=self.app.accent_color, hover_color=self.app.accent_hover,
            command=self.on_rg_plugin_toggle
        )
        self.cb_rg_plugin_only.pack(anchor="w", pady=10, padx=20)

        self.cb_rg_maxon_app = ctk.CTkCheckBox(
            self.frame_options, text=t.get("rg_maxon_app_lbl", "Установка Maxon App"),
            variable=self.app.rg_maxon_app_var, font=self.app.font_main,
            fg_color=self.app.accent_color, hover_color=self.app.accent_hover
        )
        self.cb_rg_maxon_app.pack(anchor="w", pady=10, padx=20)
        self.on_rg_plugin_toggle()

        # === ВЫБОР ДИСКА (скрывается, если диск только один) ===
        drives = [f"{d}:" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:\\")]
        if not drives: drives = ["C:"]
        
        self.drive_frame = ctk.CTkFrame(self.frame_options, fg_color="transparent")

        self.lbl_drive = ctk.CTkLabel(self.drive_frame, text=t.get("drive_lbl", "Диск установки AE:"), font=self.app.font_main)
        self.drive_var = ctk.StringVar(value=self.app.ae_drive if getattr(self.app, 'ae_drive', None) else drives[0])
        self.drive_seg = ctk.CTkSegmentedButton(
            self.drive_frame, values=drives, variable=self.drive_var, command=self.change_ae_drive,
            font=("Calibri", 12), selected_color=self.app.accent_color,
            selected_hover_color=self.app.accent_hover, unselected_color="#1a1a1a", text_color="#cccccc"
        )
        
        # Показываем ВЕСЬ ФРЕЙМ только если дисков больше одного
        if len(drives) > 1:
            self.drive_frame.pack(fill="x", pady=(10, 0))
            self.lbl_drive.pack(anchor="w", pady=(0, 5), padx=20)
            self.drive_seg.pack(anchor="w", fill="x", pady=(0, 5), padx=20)

        # Разделитель перед опасными настройками (уменьшили верхний отступ)
        self.options_separator = ctk.CTkFrame(self.frame_options, height=2, fg_color="#2a2a2a")
        self.options_separator.pack(fill="x", padx=20, pady=(15, 20))

        # Очистка кэша
        self.btn_clear_cache = ctk.CTkButton(
            self.frame_options, text=t.get("clear_cache_btn", "Очистить кэш (удалить скачанные архивы)"),
            font=("Calibri", 14, "bold"), fg_color="#552222", hover_color="#772222",
            height=36, command=self.clear_app_cache
        )
        self.btn_clear_cache.pack(anchor="w", padx=20, pady=(0, 20))

        self.populate_logs()
        self.show_changelog() 
        self.after(200, self.build_sync_ui)

    def on_rg_plugin_toggle(self):
        if self.app.rg_plugin_only_var.get():
            self.cb_rg_maxon_app.configure(state="normal")
        else:
            self.app.rg_maxon_app_var.set(False)
            self.cb_rg_maxon_app.configure(state="disabled")

    def update_drive_widget(self):
        drives = [f"{d}:" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:\\")]
        if not drives: drives = ["C:"]

        self.drive_seg.configure(values=drives)

        # Динамически скрываем или показываем ВЕСЬ фрейм выбора диска
        if len(drives) > 1:
            self.drive_frame.pack(fill="x", pady=(10, 0))
            self.lbl_drive.pack(anchor="w", pady=(0, 5), padx=20)
            self.drive_seg.pack(anchor="w", fill="x", pady=(0, 5), padx=20)
        else:
            self.drive_frame.pack_forget()

        if self.app.ae_drive not in drives:
            new_drive = drives[0]
            self.drive_var.set(new_drive)
            self.change_ae_drive(new_drive)
        else:
            self.drive_var.set(self.app.ae_drive)

    def change_ae_drive(self, val):
        self.app.ae_drive = val
        self.app.app_settings["ae_drive"] = val
        self.app.save_app_config()
        self.app.check_installed_plugins()

    def clear_app_cache(self):
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        
        confirm_msg = "Удалить все временные файлы и скачанные архивы?\n(Ваши настройки и кастомные плагины сохранятся)"
        if self.app.current_lang == "en":
            confirm_msg = "Delete all temporary files and downloaded archives?\n(Settings and custom plugins will be kept)"
            
        if not messagebox.askyesno(t.get("warn_title", "Внимание"), confirm_msg):
            return
            
        # Список файлов и папок, которые НЕЛЬЗЯ удалять
        keep_files = {"app_config.json", "settings.json", "plugins.json", "lang.json"}
        keep_dirs = {"custom_configs"}
        
        cache_dir = self.app.cache_dir
        deleted_size = 0
        
        try:
            for item in os.listdir(cache_dir):
                item_path = os.path.join(cache_dir, item)
                
                # Если это файл и его нет в белом списке - удаляем
                if os.path.isfile(item_path):
                    if item not in keep_files:
                        deleted_size += os.path.getsize(item_path)
                        os.remove(item_path)
                        
                # Если это папка и её нет в белом списке - удаляем со всем содержимым
                elif os.path.isdir(item_path):
                    if item not in keep_dirs:
                        for dirpath, _, filenames in os.walk(item_path):
                            for f in filenames:
                                fp = os.path.join(dirpath, f)
                                if not os.path.islink(fp) and os.path.exists(fp):
                                    deleted_size += os.path.getsize(fp)
                        shutil.rmtree(item_path, ignore_errors=True)
            
            mb_freed = deleted_size / (1024 * 1024)
            
            success_msg = f"Кэш успешно очищен!\nОсвобождено: {mb_freed:.2f} МБ"
            if self.app.current_lang == "en":
                success_msg = f"Cache cleared successfully!\nFreed: {mb_freed:.2f} MB"
                
            messagebox.showinfo("Инфо" if self.app.current_lang == "ru" else "Info", success_msg)
            
        except Exception as e:
            err_title = "Ошибка" if self.app.current_lang == "ru" else "Error"
            messagebox.showerror(err_title, f"Произошла ошибка при очистке кэша:\n{e}")

    def show_options(self):
        self._reset_sidebar()
        self.update_drive_widget()
        self.frame_options.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_options.configure(fg_color=self.app.accent_color, text_color="#ffffff")

    def _reset_sidebar(self):
        self.frame_changelog.grid_forget()
        self.frame_logs.grid_forget()
        self.frame_custom.grid_forget()
        self.frame_settings.grid_forget()
        self.frame_sync.grid_forget()
        self.frame_uninstall.grid_forget()
        self.frame_options.grid_forget()

        self.btn_tab_changelog.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_logs.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_custom.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_settings.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_sync.configure(fg_color="transparent", text_color="#cccccc") 
        self.btn_tab_uninstall.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_options.configure(fg_color="transparent", text_color="#cccccc")

    def show_uninstall(self):
        self._reset_sidebar()
        self.frame_uninstall.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_uninstall.configure(fg_color=self.app.accent_color, text_color="#ffffff")
        
        current_main_ver = self.app.version_var.get()
        if self.un_version_var.get() != current_main_ver:
            self.un_version_var.set(current_main_ver) 
        else:
            self.build_uninstall_ui()

    def build_uninstall_ui(self):
        for widget in self.uninstall_scroll.winfo_children(): widget.destroy()

        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        ae_ver = self.un_version_var.get()
        if ae_ver == "None":
            lbl = ctk.CTkLabel(self.uninstall_scroll, text=t.get("un_select_ae", "Please select an AE version from the list above."), text_color="#cc5555")
            lbl.pack(pady=20)
            return

        full_ver = "20" + ae_ver
        installed_any = False

        sorted_checkboxes = sorted(self.app.checkboxes, key=lambda x: x[0].lower())

        for name, var in sorted_checkboxes:
            if self.app.is_plugin_installed(name, full_ver):
                installed_any = True
                row = ctk.CTkFrame(self.uninstall_scroll, fg_color="#1a1a1a", corner_radius=6)
                row.pack(fill="x", pady=5)

                lbl = ctk.CTkLabel(row, text=name, font=("Calibri", 14, "bold"), anchor="w")
                lbl.pack(side="left", padx=15, pady=10)

                btn_del = ctk.CTkButton(
                    row, text=t.get("un_btn", "Delete"), width=80, height=28, 
                    fg_color="#882222", hover_color="#aa3333",
                    command=lambda n=name: self.request_uninstall(n, full_ver)
                )
                btn_del.pack(side="right", padx=15)

        if not installed_any:
            lbl = ctk.CTkLabel(self.uninstall_scroll, text=t.get("un_none", "No plugins installed for this version."), text_color="#aaaaaa")
            lbl.pack(pady=20)

    def request_uninstall(self, plugin_name, full_ver):
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        confirm = messagebox.askyesno(t.get("un_confirm_title", "Confirm"), f"{t.get('un_confirm_msg', 'Uninstall')} {plugin_name}?")
        if confirm:
            self.app.uninstall_plugin(plugin_name, full_ver)
            self.app.check_installed_plugins()
            self.app.after(200, self.build_uninstall_ui)

    def show_sync(self):
        self._reset_sidebar()
        self.frame_sync.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_sync.configure(fg_color=self.app.accent_color, text_color="#ffffff")

    def show_changelog(self):
        self._reset_sidebar()
        self.frame_changelog.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_changelog.configure(fg_color=self.app.accent_color, text_color="#ffffff")

    def show_logs(self):
        self._reset_sidebar()
        self.frame_logs.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_logs.configure(fg_color=self.app.accent_color, text_color="#ffffff")

    def show_custom(self):
        self._reset_sidebar()
        self.frame_custom.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_custom.configure(fg_color=self.app.accent_color, text_color="#ffffff")
        self.build_custom_ui()

    def build_custom_ui(self, plugin_to_load=None):
        # Создаем каркас интерфейса только если его еще нет (спасает от краша!)
        if not hasattr(self, 'custom_list_frame') or not self.custom_list_frame.winfo_exists():
            for w in self.frame_custom.winfo_children(): w.destroy()

            left_pane = ctk.CTkFrame(self.frame_custom, width=250, fg_color="#1a1a1a", corner_radius=0)
            left_pane.pack(side="left", fill="y")
            left_pane.grid_propagate(False)

            btn_add = ctk.CTkButton(left_pane, text="+ Новый плагин", font=self.app.font_btn, 
                                    fg_color=self.app.accent_color, hover_color=self.app.accent_hover, 
                                    command=lambda: self.load_plugin_to_form(None))
            btn_add.pack(padx=15, pady=20, fill="x")

            self.custom_list_frame = ctk.CTkScrollableFrame(left_pane, fg_color="transparent")
            self.custom_list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 20))

            self.custom_form_frame = ctk.CTkScrollableFrame(self.frame_custom, fg_color="transparent")
            self.custom_form_frame.pack(side="right", expand=True, fill="both", padx=20, pady=20)
        else:
            # Иначе просто очищаем старый список кнопок
            for w in self.custom_list_frame.winfo_children(): w.destroy()

        # Заполняем список кнопок
        for name in sorted(self.app.custom_data.keys(), key=str.casefold):
            btn = ctk.CTkButton(self.custom_list_frame, text=name, fg_color="transparent", 
                                hover_color=self.app.accent_hover, anchor="w", 
                                command=lambda n=name: self.load_plugin_to_form(n))
            btn.pack(fill="x", pady=2)

        self.load_plugin_to_form(plugin_to_load)
    
    def load_plugin_to_form(self, plugin_name=None):
        self.current_editing_plugin = plugin_name
        data = self.app.custom_data.get(plugin_name, {}) if plugin_name else {}

        for w in self.custom_form_frame.winfo_children(): w.destroy()

        if not hasattr(self, 'c_name_var'):
            self.c_name_var = ctk.StringVar()
            self.c_ver_var = ctk.StringVar()
            self.c_size_var = ctk.StringVar()
            self.c_warn_var = ctk.StringVar()
            self.c_warn_popup_var = ctk.BooleanVar()

            self.type_source_vars = {t: ctk.StringVar() for t in ["zip", "exe", "file", "reg"]}
            self.type_gdrive_vars = {t: ctk.StringVar() for t in ["zip", "exe", "file", "reg"]}
            self.type_local_vars = {t: ctk.StringVar() for t in ["zip", "exe", "file", "reg"]}
            self.type_path_vars = {t: ctk.StringVar() for t in ["zip", "exe", "file", "reg"]}
            self.type_ext_vars = {t: ctk.StringVar() for t in ["zip", "exe", "file", "reg"]} # Добавили хранилище для форматов

        self.c_name_var.set(data.get("name", ""))
        self.c_ver_var.set(data.get("version", ""))
        self.c_size_var.set(data.get("size", ""))
        self.c_warn_var.set(data.get("warning_text", ""))
        self.c_warn_popup_var.set(data.get("warning_popup", False))

        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        custom_files = data.get("custom_files", {})
        
        for t_id in ["zip", "exe", "file", "reg"]:
            c_file_data = custom_files.get(t_id, {})
            mode_val = "Google Drive" if c_file_data.get("source") == "gdrive" else t.get("local_file", "Локальный файл")
            
            self.type_source_vars[t_id].set(mode_val)
            self.type_gdrive_vars[t_id].set(f"https://drive.google.com/file/d/{c_file_data.get('gdrive_id')}/view" if c_file_data.get("gdrive_id") else "")
            self.type_local_vars[t_id].set(c_file_data.get("filename", ""))
            self.type_path_vars[t_id].set(c_file_data.get("target_path", ""))
            
            # Извлекаем сохраненное расширение
            if t_id == "file" and c_file_data.get("source") == "gdrive":
                filename = c_file_data.get("filename", "")
                ext = os.path.splitext(filename)[1]
                if ext == ".file": ext = "" # Очищаем, если там стояла стандартная заглушка
                self.type_ext_vars[t_id].set(ext)
            else:
                self.type_ext_vars[t_id].set("")

        title_text = f"Редактирование: {plugin_name}" if plugin_name else "Новый плагин"
        lbl_title = ctk.CTkLabel(self.custom_form_frame, text=title_text, font=self.app.font_title)
        lbl_title.pack(anchor="w", pady=(0, 20))

        lbl_name = ctk.CTkLabel(self.custom_form_frame, text=t.get("c_name_ph", "Название") + " *", font=("Calibri", 12), text_color="#aaaaaa")
        lbl_name.pack(anchor="w", pady=(0, 2))
        entry_name = ctk.CTkEntry(self.custom_form_frame, textvariable=self.c_name_var)
        entry_name.pack(fill="x", pady=(0, 10))

        row1 = ctk.CTkFrame(self.custom_form_frame, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 10))
        
        col_ver = ctk.CTkFrame(row1, fg_color="transparent")
        col_ver.pack(side="left", fill="x", expand=True, padx=(0, 5))
        lbl_ver = ctk.CTkLabel(col_ver, text=t.get("c_ver_ph", "Версия"), font=("Calibri", 12), text_color="#aaaaaa")
        lbl_ver.pack(anchor="w", pady=(0, 2))
        entry_ver = ctk.CTkEntry(col_ver, textvariable=self.c_ver_var)
        entry_ver.pack(fill="x")
        
        col_size = ctk.CTkFrame(row1, fg_color="transparent")
        col_size.pack(side="right", fill="x", expand=True, padx=(5, 0))
        lbl_size = ctk.CTkLabel(col_size, text=t.get("c_size_ph", "Размер"), font=("Calibri", 12), text_color="#aaaaaa")
        lbl_size.pack(anchor="w", pady=(0, 2))
        entry_size = ctk.CTkEntry(col_size, textvariable=self.c_size_var)
        entry_size.pack(fill="x")

        row2 = ctk.CTkFrame(self.custom_form_frame, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 15))
        
        lbl_warn = ctk.CTkLabel(row2, text=t.get("c_warn_ph", "Текст предупреждения (необязательно)"), font=("Calibri", 12), text_color="#aaaaaa")
        lbl_warn.pack(anchor="w", pady=(0, 2))
        
        warn_inner_row = ctk.CTkFrame(row2, fg_color="transparent")
        warn_inner_row.pack(fill="x")
        
        entry_warn = ctk.CTkEntry(warn_inner_row, textvariable=self.c_warn_var)
        entry_warn.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        cb_warn_popup = ctk.CTkCheckBox(
            warn_inner_row, text=t.get("c_warn_popup", "Показать в окне"), variable=self.c_warn_popup_var,
            fg_color=self.app.accent_color, hover_color=self.app.accent_hover
        )
        cb_warn_popup.pack(side="right")

        self.selected_types = list(data.get("c_types", ["zip"]))
        lbl_type = ctk.CTkLabel(self.custom_form_frame, text=t.get("plugin_type", "Выбор типа файлов"), font=("Calibri", 13, "bold"))
        lbl_type.pack(anchor="w", pady=(10, 5))

        type_container = ctk.CTkFrame(self.custom_form_frame, fg_color="#1a1a1a", corner_radius=6, height=34)
        type_container.pack(fill="x", pady=(0, 15))

        self.type_buttons = {}
        for t_name, t_id in [("ZIP", "zip"), ("EXE", "exe"), ("FILE", "file"), ("REG", "reg")]:
            btn = ctk.CTkButton(type_container, text=t_name, height=30,
                                fg_color=self.app.accent_color if t_id in self.selected_types else "transparent",
                                hover_color=self.app.accent_hover if t_id in self.selected_types else "#333333",
                                text_color="#ffffff" if t_id in self.selected_types else "#cccccc",
                                command=lambda tid=t_id: self._toggle_custom_type(tid))
            btn.pack(side="left", fill="both", expand=True, padx=2, pady=2)
            self.type_buttons[t_id] = btn

        self.dynamic_path_wrapper = ctk.CTkFrame(self.custom_form_frame, fg_color="transparent")
        self.dynamic_path_wrapper.pack(fill="x", pady=(0, 15))

        self._render_type_fields()

        btn_frame = ctk.CTkFrame(self.custom_form_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(20, 0))

        btn_save = ctk.CTkButton(btn_frame, text=t.get("save_btn", "Сохранить"), font=self.app.font_btn, 
                                 fg_color=self.app.accent_color, hover_color=self.app.accent_hover, 
                                 height=40, command=self.save_managed_custom_plugin)
        btn_save.pack(side="left", fill="x", expand=True, padx=(0, 5))

        if plugin_name:
            btn_dup = ctk.CTkButton(btn_frame, text="Дублировать", font=("Calibri", 14, "bold"), fg_color="#2a2a2a", 
                                    hover_color=self.app.accent_hover, height=40, command=self.duplicate_current_custom_plugin)
            btn_dup.pack(side="left", fill="x", expand=True, padx=5)

            btn_del = ctk.CTkButton(btn_frame, text="Удалить", font=("Calibri", 14, "bold"), fg_color="#2a2a2a", 
                                    hover_color="#552222", text_color="#ff5555", height=40, command=lambda: self.delete_custom_plugin(plugin_name))
            btn_del.pack(side="right", fill="x", expand=True, padx=(5, 0))

    def _render_type_fields(self):
        for w in self.dynamic_path_wrapper.winfo_children(): w.destroy()
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])

        for t_id in self.selected_types:
            if getattr(self, 'type_source_vars', None) is None or t_id not in self.type_source_vars:
                continue

            card = ctk.CTkFrame(self.dynamic_path_wrapper, fg_color="#1a1a1a", corner_radius=6)
            card.pack(fill="x", pady=(0, 10))

            lbl_title = ctk.CTkLabel(card, text=f"{t.get('setup_for', 'Настройка для')} .{t_id.upper()}", font=("Calibri", 14, "bold"), text_color=self.app.accent_color)
            lbl_title.pack(anchor="w", padx=10, pady=(10, 5))

            current_mode = self.type_source_vars[t_id].get()
            local_text = t.get("local_file", "Локальный файл")

            if current_mode not in ["Google Drive", local_text]:
                current_mode = local_text
                self.type_source_vars[t_id].set(current_mode)

            seg = ctk.CTkSegmentedButton(
                card, 
                variable=self.type_source_vars[t_id], 
                values=["Google Drive", local_text],
                command=lambda val, tid=t_id: self.after(50, self._render_type_fields), 
                selected_color=self.app.accent_color, 
                selected_hover_color=self.app.accent_hover
            )
            seg.pack(fill="x", padx=10, pady=(0, 10))
            seg.set(current_mode)

            input_container = ctk.CTkFrame(card, fg_color="transparent")
            input_container.pack(fill="x", padx=10, pady=(0, 10))

            if current_mode == "Google Drive":
                ctk.CTkLabel(input_container, text=t.get("link_lbl", "Ссылка:"), text_color="#aaaaaa").pack(side="left", padx=(0, 10))
                ctk.CTkEntry(input_container, textvariable=self.type_gdrive_vars[t_id]).pack(side="left", fill="x", expand=True)
                
                # Добавляем поле для ввода расширения, если тип - file
                if t_id == "file":
                    ctk.CTkLabel(input_container, text="Формат:", text_color="#aaaaaa").pack(side="left", padx=(10, 5))
                    ctk.CTkEntry(input_container, textvariable=self.type_ext_vars[t_id], width=70, placeholder_text=".aex").pack(side="left")
            else:
                ctk.CTkLabel(input_container, text=t.get("file_lbl", "Файл:"), text_color="#aaaaaa").pack(side="left", padx=(0, 10))
                ctk.CTkEntry(input_container, textvariable=self.type_local_vars[t_id]).pack(side="left", fill="x", expand=True, padx=(0, 10))
                ctk.CTkButton(input_container, text=t.get("browse", "Обзор"), width=60, fg_color=self.app.accent_color, hover_color=self.app.accent_hover, command=lambda tid=t_id: self._browse_local_file(tid)).pack(side="right")

            if t_id in ["zip", "file"]:
                path_frame = ctk.CTkFrame(card, fg_color="transparent")
                path_frame.pack(fill="x", padx=10, pady=(0, 10))
                ctk.CTkLabel(path_frame, text=t.get("folder_lbl", "Папка:"), text_color="#aaaaaa").pack(side="left", padx=(0, 10))
                ctk.CTkEntry(path_frame, textvariable=self.type_path_vars[t_id], placeholder_text=t.get("custom_path_ph", "Leave empty for default...")).pack(side="left", fill="x", expand=True, padx=(0, 10))
                ctk.CTkButton(path_frame, text=t.get("browse", "Обзор"), width=60, fg_color=self.app.accent_color, hover_color=self.app.accent_hover, command=lambda tid=t_id: self._browse_target_path(tid)).pack(side="right")
                
    def _toggle_custom_type(self, t_id):
        # Добавляем или удаляем тип файла из списка выбранных
        if t_id in self.selected_types:
            self.selected_types.remove(t_id)
        else:
            self.selected_types.append(t_id)
            
        # Обновляем визуальное состояние кнопок (подсветка выбранных)
        for tid, btn in self.type_buttons.items():
            if tid in self.selected_types:
                btn.configure(fg_color=self.app.accent_color, hover_color=self.app.accent_hover, text_color="#ffffff")
            else:
                btn.configure(fg_color="transparent", hover_color="#333333", text_color="#cccccc")
                
        # Перерисовываем поля ввода (ссылки, пути) под выбранные форматы
        self._render_type_fields()
        
    def _browse_target_path(self, t_id):
        folder = filedialog.askdirectory()
        if folder: self.type_path_vars[t_id].set(folder)

    def _browse_local_file(self, t_id):
        file_path = filedialog.askopenfilename()
        if file_path: self.type_local_vars[t_id].set(file_path)

    def save_managed_custom_plugin(self):
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        try:
            name = self.c_name_var.get().strip().replace(" ", "_")
            
            if not name or not self.selected_types:
                messagebox.showwarning(t.get("warn_title", "Внимание"), t.get("warn_fields", "Поля 'Название' и типы файлов обязательны!"))
                return
                
            old_name = self.current_editing_plugin
            if name != old_name and any(p[0].lower() == name.lower() for p in self.app.plugins_data):
                messagebox.showerror(t.get("err_title", "Ошибка"), t.get("err_exists", "Плагин с таким именем уже существует!"))
                return
                
            custom_files = {}
            for t_id in self.selected_types:
                mode = "gdrive" if self.type_source_vars[t_id].get() == "Google Drive" else "local"
                file_info = {"source": mode}

                if mode == "gdrive":
                    # Подставляем пользовательский формат для типа file
                    if t_id == "file":
                        ext = self.type_ext_vars[t_id].get().strip()
                        if ext and not ext.startswith("."): ext = "." + ext
                        if not ext: ext = ".file" # Если оставили пустым, ставим заглушку
                        c_filename = f"{name}_{t_id}{ext}"
                    else:
                        c_filename = f"{name}_{t_id}.{t_id}"
                        
                    file_info["filename"] = c_filename

                    raw_link = self.type_gdrive_vars[t_id].get().strip()
                    gdrive_id = self.app.extract_gdrive_id(raw_link)
                    if not gdrive_id:
                        messagebox.showerror(t.get("err_title", "Ошибка"), f"Неверная ссылка Google Drive для .{t_id}")
                        return
                    file_info["gdrive_id"] = gdrive_id
                else:
                    local_src = self.type_local_vars[t_id].get().strip()
                    ext = os.path.splitext(local_src)[1] if local_src else f".{t_id}"
                    c_filename = f"{name}_{t_id}{ext}"
                    file_info["filename"] = c_filename
                    
                    if os.path.isabs(local_src):
                        if not os.path.exists(local_src):
                            messagebox.showerror(t.get("err_title", "Ошибка"), f"Локальный файл не найден для .{t_id}")
                            return
                        dest_path = os.path.join(self.app.base_dir, c_filename)
                        try:
                            shutil.copy2(local_src, dest_path)
                        except OSError as e:
                            messagebox.showerror(t.get("err_title", "Ошибка"), f"Ошибка копирования файла: {e}")
                            return
                    elif not local_src:
                        messagebox.showerror(t.get("err_title", "Ошибка"), f"Укажите локальный файл для .{t_id}")
                        return

                target = self.type_path_vars[t_id].get().strip()
                if target: file_info["target_path"] = target
                custom_files[t_id] = file_info

            new_plugin = {
                "name": name, "version": self.c_ver_var.get().strip() or "1.0",
                "size": self.c_size_var.get().strip() or "? MB", "bat_path": "CUSTOM",
                "c_types": list(self.selected_types), "custom_files": custom_files,
                "warning_text": self.c_warn_var.get().strip(), "warning_popup": self.c_warn_popup_var.get()
            }

            target_db_path = os.path.join(self.app.custom_configs_dir, "custom_plugins.json")
            data = {"plugins": []}
            
            if old_name:
                for filename in os.listdir(self.app.custom_configs_dir):
                    if filename.endswith(".json"):
                        filepath = os.path.join(self.app.custom_configs_dir, filename)
                        try:
                            with open(filepath, "r", encoding="utf-8") as f: test_data = json.load(f)
                            if any(p.get("name") == old_name for p in test_data.get("plugins", [])):
                                target_db_path = filepath
                                data = test_data
                                break
                        except Exception: pass

            if not old_name or not data.get("plugins"):
                if os.path.exists(target_db_path):
                    try:
                        with open(target_db_path, "r", encoding="utf-8") as f:
                            loaded = json.load(f)
                            if isinstance(loaded, dict) and "plugins" in loaded: 
                                data = loaded
                    except Exception: pass

            if old_name:
                data["plugins"] = [p for p in data.get("plugins", []) if p.get("name") != old_name]
            
            data["plugins"].append(new_plugin)

            try:
                with open(target_db_path, "w", encoding="utf-8") as f: 
                    json.dump(data, f, ensure_ascii=False, indent=4)
            except OSError as e:
                messagebox.showerror(t.get("err_title", "Ошибка"), f"Не удалось сохранить JSON: {e}")
                return

            self.app.reload_custom_plugins()
            self.after(50, lambda n=name: self.build_custom_ui(n))
            if self.frame_sync.winfo_ismapped(): 
                self.after(50, self.build_sync_ui)
            
        except Exception as e:
            messagebox.showerror("Критическая ошибка", f"Произошла ошибка при сохранении:\n{e}")

    def duplicate_current_custom_plugin(self):
        if not self.current_editing_plugin:
            return
        
        # Меняем имя в поле ввода, добавляя приписку _copy
        current_name = self.c_name_var.get()
        self.c_name_var.set(f"{current_name}_copy")
        
        # Сбрасываем текущий редактируемый плагин, 
        # чтобы при нажатии "Сохранить" он сохранился как абсолютно новый
        self.current_editing_plugin = None
        
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        messagebox.showinfo(
            t.get("warn_title", "Инфо"), 
            "Плагин скопирован! Вы можете изменить нужные поля (например, название) и нажать 'Сохранить'."
        )

    def delete_custom_plugin(self, name):
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        if not messagebox.askyesno(t.get("un_confirm_title", "Подтверждение"), f"{t.get('un_confirm_msg', 'Удалить')} {name}?"): return
        
        # Ищем плагин по всем JSON файлам в директории
        for filename in os.listdir(self.app.custom_configs_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(self.app.custom_configs_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f: data = json.load(f)
                    original_len = len(data.get("plugins", []))
                    data["plugins"] = [p for p in data.get("plugins", []) if p.get("name") != name]
                    
                    if len(data.get("plugins", [])) < original_len:
                        with open(filepath, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
                        break # Плагин найден и удален, дальше искать не нужно
                except Exception as e: print(f"Error deleting: {e}")
                
        self.app.reload_custom_plugins()
        self.after(50, self.build_custom_ui)
        if self.frame_sync.winfo_ismapped(): self.after(50, self.build_sync_ui)
        
    def show_settings(self):
        self._reset_sidebar()
        self.frame_settings.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_settings.configure(fg_color=self.app.accent_color, text_color="#ffffff")
        self.build_settings_ui()

    def build_settings_ui(self):
        for widget in self.settings_scroll.winfo_children(): widget.destroy()
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        exe_installers = ["BCC", "Mocha_Pro", "Sapphire", "RedGiant", "RSMB"]
        
        for p_data in self.app.plugins_data:
            p_name = p_data[0]
            if p_name in exe_installers or p_data[2] == "CUSTOM": continue 

            row = ctk.CTkFrame(self.settings_scroll, fg_color="#1a1a1a", corner_radius=6)
            row.pack(fill="x", pady=5)

            lbl = ctk.CTkLabel(row, text=p_name, font=("Calibri", 14, "bold"), width=120, anchor="w")
            lbl.pack(side="left", padx=10, pady=10)

            var = ctk.StringVar(value=self.app.custom_plugin_paths.get(p_name, ""))
            self.path_entries[p_name] = var
            var.trace_add("write", lambda *args, name=p_name, v=var: self._save_single_path(name, v))

            entry = ctk.CTkEntry(row, textvariable=var, placeholder_text=t.get("custom_path_ph", ""), height=30)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

            btn_reset = ctk.CTkButton(row, text="✖", width=30, height=30, fg_color="#552222", hover_color="#772222", command=lambda v=var: v.set(""))
            btn_reset.pack(side="right", padx=(0, 10))

            btn = ctk.CTkButton(row, text=t.get("browse", "Browse"), width=70, height=30, fg_color="#333333", hover_color="#444444", command=lambda n=p_name, v=var: self._browse_plugin_path(n, v))
            btn.pack(side="right", padx=(0, 5))

    def _browse_plugin_path(self, plugin_name, string_var):
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        folder = filedialog.askdirectory(title=f"{t.get('select_folder', 'Select folder for')} {plugin_name}")
        if folder:
            string_var.set(folder)
            self._save_single_path(plugin_name, string_var)

    def _save_single_path(self, plugin_name, string_var):
        self.app.custom_plugin_paths[plugin_name] = string_var.get()
        self.app.save_settings()

    def reset_all_paths(self):
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        if messagebox.askyesno(t.get("reset_confirm_title", "Confirm"), t.get("reset_confirm_msg", "Reset all paths?")):
            self.app.custom_plugin_paths.clear()
            for var in self.path_entries.values(): var.set("")
            self.app.save_settings()

    def browse_specific_path(self, t_id):
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        folder = filedialog.askdirectory(title=t.get('target_folder', 'Target folder'))
        if folder: self.path_vars[t_id].set(folder)

    def build_sync_ui(self):
        for widget in self.card_plugins.winfo_children(): widget.destroy()
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        
        lbl_sync_custom = ctk.CTkLabel(self.card_plugins, text=t.get("sync_custom", "Custom Plugins"), font=("Calibri", 14, "bold"), text_color="#cccccc")
        lbl_sync_custom.pack(pady=(15, 10))

        btn_frame_custom = ctk.CTkFrame(self.card_plugins, fg_color="transparent")
        btn_frame_custom.pack(fill="x", padx=20, pady=(0, 10))

        # Добавлена общая кнопка экспорта для всего списка плагинов
        self.btn_export_custom = ctk.CTkButton(
            btn_frame_custom, text=t.get("export_btn", "Export"), font=("Calibri", 14, "bold"), 
            fg_color="#333333", hover_color="#444444", height=35, command=self.export_custom
        )
        self.btn_export_custom.pack(side="left", expand=True, fill="x", padx=(0, 5))

        self.btn_import_custom = ctk.CTkButton(
            btn_frame_custom, text=t.get("import_btn", "Import"), font=("Calibri", 14, "bold"), 
            fg_color=self.app.accent_color, hover_color=self.app.accent_hover, height=35, command=self.import_custom
        )
        self.btn_import_custom.pack(side="right", expand=True, fill="x", padx=(5, 0))

        list_frame = ctk.CTkScrollableFrame(self.card_plugins, fg_color="transparent", height=120)
        list_frame.pack(fill="x", padx=10, pady=(0, 15))
        
        if os.path.exists(self.app.custom_configs_dir):
            for filename in os.listdir(self.app.custom_configs_dir):
                if filename.endswith(".json"):
                    row = ctk.CTkFrame(list_frame, fg_color="#2a2a2a", corner_radius=6)
                    row.pack(fill="x", pady=4)
                    
                    lbl = ctk.CTkLabel(row, text=filename, font=("Calibri", 13))
                    lbl.pack(side="left", padx=10, pady=6)
                    
                    btn_del = ctk.CTkButton(
                        row, text="✖", width=28, height=28, fg_color="#882222", hover_color="#aa3333",
                        command=lambda f=filename: self.delete_config(f)
                    )
                    btn_del.pack(side="right", padx=(5, 10))
                    
                    btn_exp = ctk.CTkButton(
                        row, text=t.get("export_btn", "Export"), width=60, height=28, 
                        fg_color="#333333", hover_color="#444444",
                        command=lambda f=filename: self.export_specific_config(f)
                    )
                    btn_exp.pack(side="right", padx=(5, 0))

    def export_paths(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f: json.dump(self.app.custom_plugin_paths, f, ensure_ascii=False, indent=4)
            except OSError as e:
                print(f"File export error: {e}")

    def import_paths(self):
        filepath = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as f: data = json.load(f)
                self.app.custom_plugin_paths.update(data)
                self.app.save_settings()
                self.build_settings_ui() 
            except (OSError, json.JSONDecodeError) as e:
                print(f"File import error: {e}")

    def delete_config(self, filename):
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        if messagebox.askyesno(t.get("un_confirm_title", "Confirm"), f"{t.get('un_confirm_msg', 'Delete')} {filename}?"):
            filepath = os.path.join(self.app.custom_configs_dir, filename)
            try:
                os.remove(filepath)
                self.app.reload_custom_plugins()
                self.build_sync_ui()
            except OSError as e:
                print(f"Error deleting config: {e}")

    def edit_config(self, filename):
        t = self.app.lang_dict.get(self.app.current_lang, self.app.lang_dict["en"])
        filepath = os.path.join(self.app.custom_configs_dir, filename)
        if not os.path.exists(filepath): return
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                file_data = json.load(f)
            if not isinstance(file_data, dict) or "plugins" not in file_data:
                raise ValueError("Invalid JSON structure.")
        except Exception as e:
            messagebox.showerror(t.get("err_title", "Error"), f"Cannot parse config:\n{e}")
            return
            
        plugins_list = file_data.get("plugins", [])
        if not isinstance(plugins_list, list) or not plugins_list:
            messagebox.showinfo(t.get("warn_title", "Info"), "В этом файле нет плагинов.")
            return

        editor = ctk.CTkToplevel(self)
        editor.title(f"{t.get('editor_title', 'Config Editor')} - {filename}")
        editor.geometry("500x580")
        editor.transient(self)
        editor.grab_set()
        
        if hasattr(self.app, 'icon_path') and os.path.exists(self.app.icon_path):
            editor.after(200, lambda: editor.iconbitmap(self.app.icon_path))
            
        if sys.platform == "win32":
            def set_dark_titlebar():
                try:
                    editor.update_idletasks()
                    hwnd = int(editor.wm_frame(), 16)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
                    ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
                except Exception: pass
            editor.after(10, set_dark_titlebar)

        lbl_title = ctk.CTkLabel(editor, text="Редактор плагинов", font=self.app.font_title)
        lbl_title.pack(pady=(20, 10))
        
        plugin_names = [p.get("name", "Unknown") for p in plugins_list]
        selected_index = ctk.IntVar(value=0)

        def load_plugin_data(idx):
            apply_current()
            selected_index.set(idx)
            p = plugins_list[idx]
            
            entry_name.delete(0, "end")
            entry_name.insert(0, p.get("name", ""))
            
            entry_ver.delete(0, "end")
            entry_ver.insert(0, p.get("version", ""))
            
            entry_size.delete(0, "end")
            entry_size.insert(0, p.get("size", ""))
            
            entry_warn.delete(0, "end")
            entry_warn.insert(0, p.get("warning_text", ""))
            
            if p.get("warning_popup", False): cb_warn_popup.select()
            else: cb_warn_popup.deselect()
            
            selector.set(p.get("name", "Unknown"))
            
        selector = ctk.CTkOptionMenu(
            editor, values=plugin_names, 
            command=lambda choice: load_plugin_data(plugin_names.index(choice))
        )
        selector.pack(fill="x", padx=20, pady=(0, 20))

        form_frame = ctk.CTkFrame(editor, fg_color="transparent")
        form_frame.pack(fill="both", expand=True, padx=20)

        lbl_name = ctk.CTkLabel(form_frame, text=t.get("c_name_ph", "Название:") + " *", anchor="w")
        lbl_name.pack(fill="x")
        entry_name = ctk.CTkEntry(form_frame)
        entry_name.pack(fill="x", pady=(0, 10))

        lbl_ver = ctk.CTkLabel(form_frame, text=t.get("c_ver_ph", "Версия:"), anchor="w")
        lbl_ver.pack(fill="x")
        entry_ver = ctk.CTkEntry(form_frame)
        entry_ver.pack(fill="x", pady=(0, 10))

        lbl_size = ctk.CTkLabel(form_frame, text=t.get("c_size_ph", "Размер:"), anchor="w")
        lbl_size.pack(fill="x")
        entry_size = ctk.CTkEntry(form_frame)
        entry_size.pack(fill="x", pady=(0, 10))

        lbl_warn = ctk.CTkLabel(form_frame, text=t.get("c_warn_ph", "Текст предупреждения:"), anchor="w")
        lbl_warn.pack(fill="x")
        entry_warn = ctk.CTkEntry(form_frame)
        entry_warn.pack(fill="x", pady=(0, 10))

        cb_warn_popup = ctk.CTkCheckBox(form_frame, text=t.get("c_warn_popup", "Показать в окне"))
        cb_warn_popup.pack(anchor="w", pady=(0, 20))

        def apply_current():
            idx = selected_index.get()
            if idx < len(plugins_list):
                plugins_list[idx]["name"] = entry_name.get().strip()
                plugins_list[idx]["version"] = entry_ver.get().strip()
                plugins_list[idx]["size"] = entry_size.get().strip()
                plugins_list[idx]["warning_text"] = entry_warn.get().strip()
                plugins_list[idx]["warning_popup"] = bool(cb_warn_popup.get())
                plugin_names[idx] = plugins_list[idx]["name"]
                selector.configure(values=plugin_names)
                
        p_initial = plugins_list[0]
        entry_name.insert(0, p_initial.get("name", ""))
        entry_ver.insert(0, p_initial.get("version", ""))
        entry_size.insert(0, p_initial.get("size", ""))
        entry_warn.insert(0, p_initial.get("warning_text", ""))
        if p_initial.get("warning_popup", False): cb_warn_popup.select()
        else: cb_warn_popup.deselect()
        
        def save_changes():
            apply_current()
            for idx, p in enumerate(plugins_list):
                if not p.get("name"):
                    messagebox.showerror(t.get("err_title", "Error"), f"Плагин #{idx + 1} не имеет названия!")
                    return
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(file_data, f, ensure_ascii=False, indent=4)
                self.app.reload_custom_plugins()
                if self.frame_sync.winfo_ismapped():
                    self.build_sync_ui()
                editor.destroy()
            except OSError as e:
                messagebox.showerror(t.get("err_title", "Error"), f"Failed to save:\n{e}")

        btn_save = ctk.CTkButton(
            editor, text=t.get("save_btn", "Save"), font=self.app.font_btn,
            fg_color=self.app.accent_color, hover_color=self.app.accent_hover,
            command=save_changes, height=45
        )
        btn_save.pack(fill="x", padx=15, pady=(0, 15))

    def export_specific_config(self, filename):
        src_path = os.path.join(self.app.custom_configs_dir, filename)
        if not os.path.exists(src_path): return
        filepath = filedialog.asksaveasfilename(initialfile=filename, defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if filepath: 
            if os.path.abspath(src_path) == os.path.abspath(filepath):
                return  # Игнорируем экспорт в тот же самый файл
            try: 
                shutil.copy2(src_path, filepath)
            except Exception as e: 
                print(f"Error exporting config: {e}")
                
    def export_custom(self):
        filepath = filedialog.asksaveasfilename(
            initialfile="all_custom_plugins.json", 
            defaultextension=".json", 
            filetypes=[("JSON files", "*.json")]
        )
        
        if filepath:
            export_data = {"plugins": []}
            if os.path.exists(self.app.custom_configs_dir):
                # Собираем плагины из всех файлов
                for filename in os.listdir(self.app.custom_configs_dir):
                    if filename.endswith(".json"):
                        try:
                            with open(os.path.join(self.app.custom_configs_dir, filename), 'r', encoding='utf-8') as f:
                                data = json.load(f)
                                if "plugins" in data:
                                    export_data["plugins"].extend(data["plugins"])
                        except Exception as e:
                            print(f"Error reading {filename}: {e}")
            try:
                # Записываем общий список в выбранный файл
                with open(filepath, 'w', encoding='utf-8') as f: 
                    json.dump(export_data, f, ensure_ascii=False, indent=4)
            except OSError as e:
                print(f"Error exporting custom plugins: {e}")

    def import_custom(self):
        filepath = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as f: data = json.load(f)
                if "plugins" not in data: return
                
                filename = os.path.basename(filepath)
                dest = os.path.join(self.app.custom_configs_dir, filename)
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(dest):
                    dest = os.path.join(self.app.custom_configs_dir, f"{base}_{counter}{ext}")
                    counter += 1
                    
                shutil.copy2(filepath, dest)
                self.app.reload_custom_plugins()
                self.build_sync_ui()
            except (OSError, json.JSONDecodeError) as e:
                print(f"Error importing custom plugins: {e}")

    def populate_logs(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        for entry in self.app.persistent_log_history: self.log_textbox.insert("end", entry.get(self.app.current_lang, entry["en"]) + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def append_log(self, text):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", text)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def export_persistent_logs(self):
        if not self.app.persistent_log_history: return
        file_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(f"--- AE Plugins Installer Persistent Logs ({self.app.CURRENT_VERSION}) ---\n\n")
                    for entry in self.app.persistent_log_history: f.write(entry.get(self.app.current_lang, entry["en"]) + "\n")
            except OSError as e:
                print(f"Error exporting logs: {e}")

    def update_last_log(self, text):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("end-2c linestart", "end-1c")
        self.log_textbox.insert("end-1c", text)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

class AksiomInstaller(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.withdraw() # Полностью скрываем главное окно
        
        self.splash = ctk.CTkToplevel(self)
        self.splash.title("Загрузка...")
        self.splash.geometry("340x160")
        self.splash.resizable(False, False)      # Нельзя растягивать, но МОЖНО свернуть
        self.splash.attributes("-topmost", True) # Держим поверх других окон
        
        # Подхватываем иконку для окна загрузки в таскбаре
        bundle_dir = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(bundle_dir, "logo.ico")
        if os.path.exists(icon_path):
            self.splash.iconbitmap(icon_path)

        # Делаем темную шапку окна (чтобы не было белой полосы Windows)
        if sys.platform == "win32":
            def set_splash_dark_titlebar():
                try:
                    self.splash.update_idletasks()
                    hwnd = int(self.splash.wm_frame(), 16)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
                except Exception: pass
            self.splash.after(10, set_splash_dark_titlebar)
        
        # Центрируем по центру экрана
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = int((screen_width / 2) - (340 / 2))
        y = int((screen_height / 2) - (160 / 2))
        self.splash.geometry(f"+{x}+{y}")
        
        # Наполнение сплэш-скрина
        self.splash.grid_rowconfigure(0, weight=1)
        self.splash.grid_columnconfigure(0, weight=1)
        
        splash_frame = ctk.CTkFrame(self.splash, fg_color="#1a1a1a", corner_radius=10)
        splash_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        lbl_splash_title = ctk.CTkLabel(splash_frame, text="Aksiom Installer", font=("Calibri", 20, "bold"), text_color="#6658cc")
        lbl_splash_title.pack(pady=(20, 5))
        
        lbl_splash_status = ctk.CTkLabel(splash_frame, text="Инициализация и загрузка баз данных...", font=("Calibri", 13), text_color="#aaaaaa")
        lbl_splash_status.pack(pady=(0, 20))
        
        self.splash.update() # Принудительно отрисовываем окно

        self.CURRENT_VERSION = "Beta 6.0" 
        self.DB_URL = "https://raw.githubusercontent.com/Aks-iom/aksiom-installer-data/refs/heads/main/plugins.json"
        
        self.CHANGELOG_TEXT = {
            "ru": (
                "Версия Beta 6.0:\n"
                "-Реворк раздела Конфигуратора своих плагинов \n"
                "-Установка более старых RSMB,Universe\n"
                "-Очистка кэша"
                "-Изменение работы с окнами\n"
                "-Добавление окна загрузки приложения\n"
                "- Минорные обновления и баг фиксы\n\n"
                "-Версия Fake-Pre-release:\n"
                "- Кнопка принудительной установки\n"
                "- Раздел удаления\n"
                "- Поиск в меню\n"
                "- Минорные обновления и баг фиксы\n\n"
                "Версия Beta 5.0:\n"
                "- Добавление 26-ой версии АЕ в качестве эксперимента\n"
                "- Окно дополнительных настроек\n"
                "- Возможность добавления своих плагинов\n"
                "- Возможность изменения пути установки стандартных плагинов\n"
                "- Список изменений\n"
                "- Импорт и экспорт данных\n"
                "- Добавление версий и размера в списке плагинов\n"
                "- Улучшение работы с Google Drive\n"
                "- Добавление папки кэша\n"
                "- Исправление багов и минорные обновления\n"
            ),
            "en": (
                "Version Beta 6.0:\n"
                "-Reworked Custom Plugins Configurator Section\n"
                "-Installing Older RSMB, Universe\n"
                "-Clearing the Cache"
                "-Changing Window Handling\n"
                "-Adding an Application Loading Window\n"
                "- Minor updates and bug fixes\n\n"
                "Version Fake-Pre-release:\n"
                "- Force install button\n"
                "- Uninstall section\n"
                "- Menu search\n"
                "- Minor updates and bug fixes\n\n"
                "Version Beta 5.0:\n"
                "- Adding AE version 26 as an experiment\n"
                "- Additional settings window\n"
                "- Ability to add custom plugins\n"
                "- Ability to change standard plugins installation path\n"
                "- Changelog\n"
                "- Data import and export\n"
                "- Added versions and sizes to the plugins list\n"
                "- Improved Google Drive integration\n"
                "- Added cache folder\n"
                "- Bug fixes and minor updates\n"
            )
        }

        self.title("Ae plugins installer Beta 6")
        self.geometry("1050x720")
        self.resizable(True, True)
        self.minsize(820, 600)
        self.configure(fg_color="#242424")
        
        self.font_main = ("Calibri", 14)
        self.font_title = ("Calibri", 16, "bold")
        self.font_btn = ("Calibri", 18, "bold")
        
        self.accent_color = "#6658cc"
        self.accent_hover = "#5346a6"

        self.log_history = []              
        self.persistent_log_history = []   
        self.checkbox_widgets = {} 
        self.plugin_rows = {}
        
        try:
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            sys_lang = locale.windows_locale.get(lang_id, "en")
            self.current_lang = "ru" if sys_lang.startswith("ru") else "en"
        except Exception:
            self.current_lang = "en" 

        if getattr(sys, 'frozen', False):
            self.app_dir = os.path.dirname(sys.executable)
            bundle_dir = sys._MEIPASS
        else:
            self.app_dir = os.path.dirname(os.path.abspath(__file__))
            bundle_dir = self.app_dir

        self.cache_dir = os.path.join(self.app_dir, "Aksiom-installer-cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.base_dir = self.cache_dir
        
        self.custom_configs_dir = os.path.join(self.base_dir, "custom_configs")
        os.makedirs(self.custom_configs_dir, exist_ok=True)
        old_custom_db = os.path.join(self.base_dir, "custom_plugins.json")
        if os.path.exists(old_custom_db):
            try: shutil.move(old_custom_db, os.path.join(self.custom_configs_dir, "custom_plugins.json"))
            except Exception: pass
            
        self.app_config_file = os.path.join(self.base_dir, "app_config.json")
        self.app_settings = self.load_app_config()
        self.old_rsmb_var = ctk.BooleanVar(value=self.app_settings.get("old_rsmb", False))
        self.old_rsmb_var.trace_add("write", lambda *args: [self.save_app_config(), self.update_all_plugin_labels()])
        
        self.rg_plugin_only_var = ctk.BooleanVar(value=self.app_settings.get("rg_plugin_only", True))
        self.rg_plugin_only_var.trace_add("write", lambda *args: [self.save_app_config(), self.update_all_plugin_labels()])
        
        self.rg_maxon_app_var = ctk.BooleanVar(value=self.app_settings.get("rg_maxon_app", True))
        self.rg_maxon_app_var.trace_add("write", lambda *args: [self.save_app_config(), self.update_all_plugin_labels()])
        
        self.ae_drive = self.app_settings.get("ae_drive", "")
        
        self.lang_dict = self.load_language_file()
        
        self.custom_install_path_var = ctk.StringVar()
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.icon_path = os.path.join(bundle_dir, "logo.ico")
        if os.path.exists(self.icon_path): self.iconbitmap(self.icon_path)

        self.plugins_data = []
        self.plugin_keywords = {}
        self.gdrive_file_ids = {}
        self.custom_data = {}

        self.load_plugins_database()
        self.create_main_tabs()
        
        self.version_var.trace_add("write", lambda *args: self.check_installed_plugins())
        self.check_installed_plugins()
        self.check_for_updates()

        self.settings_file = os.path.join(self.base_dir, "settings.json")
        self.custom_plugin_paths = self.load_settings()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._fix_russian_hotkeys()

        self.after(200, self._close_splash_and_show)
        
    def _close_splash_and_show(self):
        # 1. Закрываем окно загрузки Tkinter (если оно активно)
        try:
            self.splash.destroy()
        except Exception:
            pass
        
        # 2. ВАЖНО: Закрываем картинку-заставку от PyInstaller!
        try:
            import pyi_splash
            pyi_splash.close()
        except ImportError:
            pass
        
        # 3. Показываем основное окно
        self.deiconify() 
        self.attributes("-alpha", 1.0) 
        self.check_ae_drive()

    def load_language_file(self):
        lang_path = os.path.join(self.base_dir, "lang.json")
        default_dict = {
            "ru": {
                "title": "Ae plugins installer Beta 6.0", "version_lbl": "Выбор версии After Effects",
                "plugins_lbl": "Выбор плагинов", "select_all": "Выбрать все", "wait": "Ожидание...",
                "install_btn": "Установить выбранные", "log_lbl": "Журнал событий", "clear_log_btn": "Очистить логи",
                "export_log_btn": "Сохранить логи", "source_btn": "Источник", "complete": "Операция завершена", "tab_install": "Установка",
                "tab_advanced": "Дополнительно",
                "advanced_btn": "Дополнительно", "tab_changelog": "Список изменений", "tab_logs": "Логи",
                "tab_custom": "Свои плагины", "tab_settings": "Индивидуальные пути", "tab_sync": "Экспорт / Импорт",
                "tab_uninstall": "Удаление", "settings_title": "Индивидуальные пути",
                "custom_title": "Конфигуратор пользовательских плагинов", "c_name_ph": "Название",
                "c_ver_ph": "Версия", "c_size_ph": "Размер", "plugin_type": "Выбор типа файлов",
                "local_file": "Локальный файл", "custom_add_btn": "Создать и добавить",
                "custom_path_ph": "Оставьте пустым для стандарта...", "browse": "Обзор",
                "search_ph": "Поиск...", "un_title": "Удаление плагинов",
                "un_desc": "Показаны плагины, установленные для выбранной версии AE.",
                "un_select_ae": "Выберите версию AE из списка выше.",
                "un_btn": "Удалить", "un_none": "Нет установленных плагинов для этой версии.",
                "un_confirm_title": "Подтверждение", "un_confirm_msg": "Вы уверены, что хотите удалить",
                "un_warn_exe": "Этот плагин устанавливался через сложный .exe файл.\nПожалуйста, удалите его через стандартную 'Установку и удаление программ' Windows, чтобы не повредить реестр.",
                "sync_title": "Управление данными", "sync_paths": "Пользовательские пути установки",
                "export_btn": "Экспорт", "import_btn": "Импорт", "sync_custom": "Пользовательские плагины",
                "sync_warn": "Примечание: Локальные файлы не переносятся.", "folder_lbl": "Папка:",
                "link_lbl": "Ссылка:", "file_lbl": "Файл:", "reset_all": "Сбросить всё",
                "reset_confirm_title": "Подтверждение", "reset_confirm_msg": "Сбросить все пути?",
                "edit_btn": "Изменить", "save_btn": "Сохранить", "editor_title": "Редактор конфига",
                "warn_title": "Внимание", "warn_fields": "Поля 'Название' и типы файлов обязательны!",
                "c_warn_ph": "Текст предупреждения (необязательно)", "c_warn_popup": "Показать в окне",
                "err_title": "Ошибка", "err_exists": "Плагин с таким именем уже существует!",
                "select_file": "Выберите файл", "select_folder": "Выберите папку для",
                "target_folder": "Целевая папка", "setup_for": "Настройка для", "custom_add_success": "Плагин '{name}' успешно добавлен!",
                "installing": "Установка", "exit_warn": "Установка не завершена. Выйти?",
                "force_install": "Принудительная установка",
                "rsmb_warn": "Мне не удалось сделать всю установку автоматически, поэтому вам придется нажать Extract самому (RSMB).",
                "tab_options": "Прочее", "options_title": "Прочие настройки", "old_rsmb_lbl": "Старый установщик RSMB",
                "rg_plugin_only_lbl": "Установка и активация плагинов (RedGiant/Universe)",
                "rg_maxon_app_lbl": "Установка Maxon App", "err_one_drive": "Найден только один диск. Изменение невозможно.",
                "drive_title": "Выбор диска",
                "drive_prompt": "На каком диске установлен After Effects?", "drive_lbl": "Диск установки AE:"
            },
            "en": {
                "title": "Ae plugins Installer Beta 6.0", "version_lbl": "Select After Effects Version",
                "plugins_lbl": "Select Plugins", "select_all": "Select All", "wait": "Waiting...",
                "install_btn": "Install Selected", "log_lbl": "Event Log", "clear_log_btn": "Clear Logs", "tab_install": "Installation",
                "tab_advanced": "Advanced",
                "export_log_btn": "Export Logs", "source_btn": "Source", "complete": "Operation Complete",
                "advanced_btn": "Advanced", "tab_changelog": "Changelog", "tab_logs": "Logs",
                "tab_custom": "Custom Plugins", "tab_settings": "Individual Paths", "tab_sync": "Export / Import",
                "tab_uninstall": "Uninstall", "settings_title": "Individual Paths",
                "custom_title": "Custom Plugin Configurator", "c_name_ph": "Name",
                "c_ver_ph": "Version", "c_size_ph": "Size", "plugin_type": "File types",
                "local_file": "Local File", "custom_add_btn": "Create and Add",
                "custom_path_ph": "Leave empty for default...", "browse": "Browse",
                "search_ph": "Search...", "un_title": "Uninstall Plugins",
                "un_desc": "Showing plugins installed for the selected AE version.",
                "un_select_ae": "Please select an AE version from the list above.",
                "un_btn": "Delete", "un_none": "No plugins installed for this version.",
                "un_confirm_title": "Confirm", "un_confirm_msg": "Are you sure you want to uninstall",
                "un_warn_exe": "This plugin was installed via a complex .exe installer.\nPlease uninstall it using the Windows 'Add or Remove Programs' panel to avoid registry issues.",
                "sync_title": "Data Management", "sync_paths": "Custom Installation Paths",
                "export_btn": "Export", "import_btn": "Import", "sync_custom": "Custom Plugins",
                "sync_warn": "Note: Local files are not transferred.", "folder_lbl": "Folder:",
                "link_lbl": "Link:", "file_lbl": "File:", "reset_all": "Reset All",
                "reset_confirm_title": "Confirm", "reset_confirm_msg": "Reset all paths?",
                "edit_btn": "Edit", "save_btn": "Save", "editor_title": "Config Editor",
                "warn_title": "Warning", "warn_fields": "'Name' and file types are required!",
                "c_warn_ph": "Warning text (optional)", "c_warn_popup": "Show in window",
                "err_title": "Error", "err_exists": "Plugin with this name already exists!",
                "select_file": "Select file", "select_folder": "Select folder for",
                "target_folder": "Target folder", "setup_for": "Setup for", "custom_add_success": "Plugin '{name}' successfully added!",
                "installing": "Installing", "exit_warn": "Installation not finished. Exit?",
                "force_install": "Force Install",
                "rsmb_warn": "I could not automate the whole installation, so you will have to click Extract yourself (RSMB).",
                "tab_options": "Misc", "options_title": "Misc Settings", "old_rsmb_lbl": "Old RSMB installer",
                "rg_plugin_only_lbl": "Install and activate plugins only (RedGiant/Universe)",
                "rg_maxon_app_lbl": "Install Maxon App", "err_one_drive": "Only one drive found. Change is not possible.",
                "drive_title": "Select Drive",
                "drive_prompt": "Which drive is After Effects installed on?", "drive_lbl": "AE Installation Drive:"
            }
        }
        
        current_dict = default_dict.copy()
        if os.path.exists(lang_path):
            try:
                with open(lang_path, 'r', encoding='utf-8') as f: 
                    loaded_data = json.load(f)
                    for lang in ["ru", "en"]:
                        if lang in loaded_data: current_dict[lang].update(loaded_data[lang])
            except json.JSONDecodeError as e:
                print(f"Failed to load language json: {e}")
            except OSError as e:
                print(f"Error accessing lang.json: {e}")
            
        try:
            with open(lang_path, 'w', encoding='utf-8') as f: 
                json.dump(current_dict, f, ensure_ascii=False, indent=4)
        except OSError as e:
            print(f"Error writing to lang.json: {e}")
        
        return current_dict

    def load_app_config(self):
        if os.path.exists(self.app_config_file):
            try:
                with open(self.app_config_file, 'r', encoding='utf-8') as f: return json.load(f)
            except Exception: pass
        return {}

    def save_app_config(self):
        self.app_settings["old_rsmb"] = self.old_rsmb_var.get()
        self.app_settings["rg_plugin_only"] = self.rg_plugin_only_var.get()
        self.app_settings["rg_maxon_app"] = self.rg_maxon_app_var.get()
        try:
            with open(self.app_config_file, 'w', encoding='utf-8') as f: json.dump(self.app_settings, f, ensure_ascii=False)
        except Exception: pass

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f: return json.load(f)
            except json.JSONDecodeError as e: 
                print(f"Error reading settings: {e}")
            except OSError as e:
                print(f"OS Error loading settings: {e}")
        return {}

    def save_settings(self):
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f: json.dump(self.custom_plugin_paths, f, ensure_ascii=False, indent=4)
        except OSError as e: 
            print(f"Error saving settings: {e}")

    def on_closing(self):
        if self.btn_install.cget("state") == "disabled":
            t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
            msg = t.get("exit_warn", "Installation not finished. Exit?")
            title = t.get("warn_title", "Warning")
            if not messagebox.askyesno(title, msg): return
        self.destroy() 
        os._exit(0)

    def extract_gdrive_id(self, url):
        if not url: return ""
        match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
        if match: return match.group(1)
        match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
        if match: return match.group(1)
        if "http" not in url and "/" not in url: return url
        return ""

    def get_pf(self):
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        if self.ae_drive: pf = self.ae_drive + os.path.splitdrive(pf)[1]
        return pf

    def get_pf86(self):
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        if self.ae_drive: pf86 = self.ae_drive + os.path.splitdrive(pf86)[1]
        return pf86

    def _generate_keywords_for_plugin(self, name):
        base_kw = name.lower()
        kws = [base_kw.replace("_", " ").strip(), base_kw, base_kw.replace("_", "")]
        if "_" in base_kw: kws.append(base_kw.split("_")[0])
        return list(set(kws))

    def check_ae_drive(self):
        if not self.ae_drive:
            drives = [f"{d}:" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:\\")]
            if not drives: drives = ["C:"]
            if len(drives) == 1:
                self.ae_drive = drives[0]
                self.app_settings["ae_drive"] = self.ae_drive
                self.save_app_config()
                self.check_installed_plugins()
            else:
                self.prompt_ae_drive(drives)

    def prompt_ae_drive(self, drives):
        dialog = ctk.CTkToplevel(self)
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
        dialog.title(t.get("drive_title", "Выбор диска"))
        dialog.geometry("380x220")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.focus_force()
        
        if hasattr(self, 'icon_path') and os.path.exists(self.icon_path):
            dialog.after(200, lambda: dialog.iconbitmap(self.icon_path))
            
        if sys.platform == "win32":
            def set_dark_titlebar():
                try:
                    dialog.update_idletasks()
                    hwnd = int(dialog.wm_frame(), 16)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
                    ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
                except Exception: pass
            dialog.after(10, set_dark_titlebar)
            
        content_frame = ctk.CTkFrame(dialog, fg_color="#1a1a1a", corner_radius=8)
        content_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        lbl = ctk.CTkLabel(content_frame, text=t.get("drive_prompt", "На каком диске установлен After Effects?"), font=self.font_main)
        lbl.pack(pady=(25, 15))
        
        drive_var = ctk.StringVar(value=drives[0])
        drive_seg = ctk.CTkSegmentedButton(
            content_frame, values=drives, variable=drive_var,
            font=("Calibri", 12), selected_color=self.accent_color,
            selected_hover_color=self.accent_hover, unselected_color="#1a1a1a", text_color="#cccccc"
        )
        drive_seg.pack(fill="x", pady=(0, 20))
        
        def on_ok():
            self.ae_drive = drive_var.get()
            self.app_settings["ae_drive"] = self.ae_drive
            self.save_app_config()
            dialog.grab_release()
            dialog.destroy()
            self.check_installed_plugins()
        
        btn = ctk.CTkButton(
            content_frame, text="OK", command=on_ok, font=self.font_btn, 
            fg_color=self.accent_color, hover_color=self.accent_hover,
            width=140, height=36, corner_radius=6
        )
        btn.pack(pady=(0, 20))

    def get_dynamic_paths(self, ae_version):
        custom_path = self.custom_install_path_var.get().strip()
        
        # Динамически меняем версию AE в глобальном пользовательском пути
        if custom_path and ae_version != "None":
            custom_path = re.sub(r'(?i)(After Effects\s*)20\d{2}', rf'\g<1>{ae_version}', custom_path)
            
        pf = self.get_pf()
        base_dir = custom_path if custom_path else os.path.join(pf, "Adobe", f"Adobe After Effects {ae_version}")
        
        plugins_dir = os.path.join(base_dir, "Support Files", "Plug-ins") if not custom_path else custom_path
        scripts_dir = os.path.join(base_dir, "Support Files", "Scripts", "ScriptUI Panels") if not custom_path else os.path.join(custom_path, "Scripts", "ScriptUI Panels")
        
        return plugins_dir, scripts_dir
    
    def resolve_target_path(self, plugin_name, default_path, full_ae_version):
        custom_path = self.custom_plugin_paths.get(plugin_name, "").strip()
        if custom_path:
            if full_ae_version != "None": custom_path = re.sub(r'(?i)(After Effects\s*)20\d{2}', rf'\g<1>{full_ae_version}', custom_path)
            return custom_path
        return default_path

    def load_plugins_database(self):
        local_db_path = os.path.join(self.base_dir, "plugins.json")
        data = None
        if os.path.exists(local_db_path):
            try:
                with open(local_db_path, 'r', encoding='utf-8') as f: data = json.load(f)
            except (OSError, json.JSONDecodeError) as e: 
                print(f"Error loading local plugins.json: {e}")

        threading.Thread(target=self._update_db_in_background, args=(local_db_path,), daemon=True).start()

        if not data:
            try:
                req = urllib.request.Request(self.DB_URL, headers={'User-Agent': 'AksiomInstaller'})
                with urllib.request.urlopen(req, timeout=3) as response: data = json.loads(response.read().decode('utf-8'))
                with open(local_db_path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось загрузить базу плагинов: {e}")
                sys.exit()

        self._parse_plugins_data(data)

    def _update_db_in_background(self, local_db_path):
        try:
            req = urllib.request.Request(self.DB_URL, headers={'User-Agent': 'AksiomInstaller'})
            with urllib.request.urlopen(req, timeout=5) as response: new_data = json.loads(response.read().decode('utf-8'))
            with open(local_db_path, 'w', encoding='utf-8') as f: json.dump(new_data, f, ensure_ascii=False, indent=4)
        except Exception as e: 
            print(f"Background DB update failed: {e}")

    def _parse_plugins_data(self, data):
        if data and "plugins" in data:
            for p in data["plugins"]:
                name = p["name"]
                self.plugins_data.append((name, p.get("version", "1.0"), p.get("bat_path", ""), p.get("needs_version", False), p.get("size", ""), p.get("md5", None)))
                
                base_kw = name.lower()
                default_kws = [base_kw.replace("_", " ").strip(), base_kw, base_kw.replace("_", "")]
                if name == "RedGiant": default_kws.extend(["trapcode", "magic bullet", "vfx", "pluraleyes", "colorista"])
                elif name == "Universe": default_kws.extend(["red giant universe", "universe"])
                
                json_kws = p.get("keywords", [])
                if name == "RedGiant" and "red giant" in json_kws:
                    json_kws.remove("red giant")
                    
                self.plugin_keywords[name] = list(set(default_kws + json_kws))
                self.gdrive_file_ids[name] = p.get("gdrive_id", "")

        if os.path.exists(self.custom_configs_dir):
            for filename in os.listdir(self.custom_configs_dir):
                if filename.endswith(".json"):
                    filepath = os.path.join(self.custom_configs_dir, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f: c_data = json.load(f)
                        for p in c_data.get("plugins", []):
                            name = p["name"]
                            self.plugins_data.append((name, p.get("version", "1.0"), "CUSTOM", False, p.get("size", ""), None))
                            
                            base_kw = name.lower()
                            default_kws = [base_kw.replace("_", " ").strip(), base_kw, base_kw.replace("_", "")]
                            
                            json_kws = p.get("keywords", [])
                            self.plugin_keywords[name] = list(set(default_kws + json_kws))
                            self.gdrive_file_ids[name] = p.get("gdrive_id", "")
                            self.custom_data[name] = p
                    except (OSError, json.JSONDecodeError) as e:
                        print(f"Error parsing {filename}: {e}")

    def get_plugin_display_text(self, plugin_name, version, bat_path, size):
        prefix = "★ " if bat_path == "CUSTOM" else ""
        ver_text = "" if version == "1.0" else f" [v{version}]"
        suffix = ""
        if plugin_name == "RSMB" and getattr(self, 'old_rsmb_var', None) and self.old_rsmb_var.get():
            suffix += " [Old]"
        if plugin_name in ["Universe", "RedGiant"]:
            if getattr(self, 'rg_maxon_app_var', None) and self.rg_maxon_app_var.get():
                suffix += " [Old maxon]"
            elif getattr(self, 'rg_plugin_only_var', None) and self.rg_plugin_only_var.get():
                suffix += " [Old]"
        return f"{prefix}{plugin_name}{ver_text}  ({size}){suffix}"

    def update_all_plugin_labels(self, *args):
        if not hasattr(self, 'checkbox_widgets'): return
        for plugin_data in self.plugins_data:
            name, ver, bat, _, size, _ = plugin_data
            if name in self.checkbox_widgets:
                self.checkbox_widgets[name].configure(text=self.get_plugin_display_text(name, ver, bat, size))

    def reload_custom_plugins(self):
        for name in list(self.custom_data.keys()):
            # 1. Забываем ссылку на чекбокс, но НЕ вызываем destroy() дважды
            if name in self.checkbox_widgets:
                del self.checkbox_widgets[name]
                
            # 2. Уничтожаем фрейм (он сам безопасно удалит чекбокс внутри себя)
            if name in self.plugin_rows:
                try:
                    self.plugin_rows[name].destroy()
                except Exception:
                    pass
                del self.plugin_rows[name]
                
            self.checkboxes = [(n, v) for n, v in self.checkboxes if n != name]
            self.plugins_data = [p for p in self.plugins_data if p[0] != name]
            
        self.custom_data.clear()
        
        if not os.path.exists(self.custom_configs_dir): return
        
        for filename in os.listdir(self.custom_configs_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(self.custom_configs_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f: c_data = json.load(f)
                    for p in c_data.get("plugins", []):
                        name = p["name"]
                        if name not in self.custom_data:
                            self.plugins_data.append((name, p.get("version", "1.0"), "CUSTOM", False, p.get("size", ""), None))
                            
                            base_kw = name.lower()
                            default_kws = [base_kw.replace("_", " ").strip(), base_kw, base_kw.replace("_", "")]
                            if "_" in base_kw: default_kws.append(base_kw.split("_")[0])
                            json_kws = p.get("keywords", [])
                            self.plugin_keywords[name] = list(set(default_kws + json_kws))
                            
                            self.gdrive_file_ids[name] = p.get("gdrive_id", "")
                            self.custom_data[name] = p
                            self._add_plugin_ui_row(name, p.get('version', '1.0'), "CUSTOM", p.get('size', ''))
                except (OSError, json.JSONDecodeError) as e:
                     print(f"Error reloading custom plugins from {filename}: {e}")
        self.check_installed_plugins()

    def create_main_tabs(self):
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
        
        # Настраиваем корневую сетку окна
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1) # Основной контент (растягивается)
        self.grid_rowconfigure(1, weight=0) # Глобальный футер внизу (фиксированный)

        # --- Контейнер для меняющегося контента ---
        self.content_container = ctk.CTkFrame(self, fg_color="transparent")
        self.content_container.grid(row=0, column=0, sticky="nsew", padx=20, pady=(20, 10))
        
        # Фрейм Установки
        self.install_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.install_frame.grid_columnconfigure(0, weight=0, minsize=360) # Фиксируем ширину левой части для нужных пропорций
        self.install_frame.grid_columnconfigure(1, weight=1) # Правая часть (логи) тянется
        self.install_frame.grid_rowconfigure(0, weight=1)
        
        # 1. ВАЖНО: Сначала собираем виджеты Установки (именно там создается version_var)
        self.create_install_tab_widgets(self.install_frame)

        # 2. Теперь безопасно создаем фрейм Настроек (он возьмет готовый version_var)
        self.advanced_frame = AdvancedFrame(self.content_container, self)
        
        # 3. Изначально показываем меню установки
        self.install_frame.pack(fill="both", expand=True)

        # --- ГЛОБАЛЬНЫЙ ФУТЕР (Здесь будут вкладки и логи) ---
        self.global_footer = ctk.CTkFrame(self, fg_color="transparent")
        self.global_footer.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 20))

        # Ссылки (перенесли их налево в общий футер)
        links_frame = ctk.CTkFrame(self.global_footer, fg_color="transparent")
        links_frame.pack(side="left")
        ctk.CTkButton(links_frame, text="GitHub", font=("Calibri", 13, "underline"), width=0, height=20, fg_color="transparent", text_color="#888888", command=lambda: webbrowser.open("https://github.com/Aks-iom/Aks-iom-AE-Plugins-install-script")).pack(side="left", padx=(0, 10))
        ctk.CTkButton(links_frame, text="Telegram", font=("Calibri", 13, "underline"), width=0, height=20, fg_color="transparent", text_color="#888888", command=lambda: webbrowser.open("https://t.me/AE_plugins_script")).pack(side="left", padx=(0, 10))
        ctk.CTkButton(links_frame, text=t.get("source_btn", "Source"), font=("Calibri", 13, "underline"), width=0, height=20, fg_color="transparent", text_color="#888888", command=lambda: webbrowser.open("https://satvrn.li/windows")).pack(side="left")

        # Кнопка очистки логов (справа)
        self.btn_clear_log = ctk.CTkButton(self.global_footer, text=t.get("clear_log_btn", "Clear"), font=self.font_main, fg_color="#333333", hover_color="#444444", height=30, width=0, command=self.clear_logs)
        self.btn_clear_log.pack(side="right", padx=(15, 0))

        # Вкладки (переключатель окон), ставим их перед логами
        self.view_mode_var = ctk.StringVar(value=t.get("tab_install", "Установка"))
        self.view_switcher = ctk.CTkSegmentedButton(
            self.global_footer, 
            values=[t.get("tab_install", "Установка"), t.get("tab_advanced", "Дополнительно")],
            variable=self.view_mode_var,
            command=self.switch_main_view,
            selected_color=self.accent_color,
            selected_hover_color=self.accent_hover,
            fg_color="#333333",              # Общий фон подложки переключателя
            unselected_color="#333333",      # Фон неактивной вкладки
            unselected_hover_color="#444444" # Цвет при наведении на неактивную вкладку
        )
        self.view_switcher.pack(side="right")

    def switch_main_view(self, selected_view):
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
        if selected_view == t.get("tab_install", "Установка"):
            self.advanced_frame.pack_forget()
            self.install_frame.pack(fill="both", expand=True)
        elif selected_view == t.get("tab_advanced", "Дополнительно"):
            self.install_frame.pack_forget()
            self.advanced_frame.pack(fill="both", expand=True)

    def create_install_tab_widgets(self, master_tab):
        left_width = 340
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])

        self.left_frame = ctk.CTkFrame(master_tab, fg_color="transparent")
        self.left_frame.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="nsew")
        self.lbl_version = ctk.CTkLabel(self.left_frame, text=t.get("version_lbl", "Version"), font=self.font_title)
        self.lbl_version.pack(anchor="w", pady=(0, 5))

        self.version_var = ctk.StringVar(value="None")
        versions = ["None", "20", "21", "22", "23", "24", "25" , "26"]
        self.segmented_button = ctk.CTkSegmentedButton(
            self.left_frame, values=versions, variable=self.version_var,
            font=("Calibri", 12), selected_color=self.accent_color,
            selected_hover_color=self.accent_hover, unselected_color="#1a1a1a", text_color="#cccccc"
        )
        self.segmented_button.pack(anchor="w", fill="x", pady=(0, 15))

        self.plugins_header_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        self.plugins_header_frame.pack(anchor="w", fill="x", pady=(0, 5))

        self.lbl_plugins = ctk.CTkLabel(self.plugins_header_frame, text=t.get("plugins_lbl", "Plugins"), font=self.font_title)
        self.lbl_plugins.pack(side="left")

        self.search_container = ctk.CTkFrame(self.plugins_header_frame, fg_color="transparent")
        self.search_container.pack(side="right")

        self.lbl_search_icon = ctk.CTkLabel(self.search_container, text="🔍", font=("Segoe UI Emoji", 14))
        self.lbl_search_icon.pack(side="left", padx=(0, 5))

        self.search_var = ctk.StringVar()
        self.entry_search = ctk.CTkEntry(
            self.search_container, textvariable=self.search_var, 
            placeholder_text=t.get("search_ph", "Search..."), 
            height=28, width=140, corner_radius=14, border_width=1, fg_color="#1e1e1e"
        )
        self.entry_search.pack(side="left")
        self.search_var.trace_add("write", self.filter_plugins)

        # Убрали фиксированный height=230
        self.scrollable_checkbox_frame = ctk.CTkScrollableFrame(self.left_frame, width=left_width, fg_color="#1a1a1a", corner_radius=8)
        # Добавили fill="both" и expand=True, чтобы список заполнял все пустое место
        self.scrollable_checkbox_frame.pack(fill="both", expand=True, pady=(0, 15))

        self.checkboxes = []
        self.select_all_var = ctk.BooleanVar(value=False)
        self.cb_select_all = ctk.CTkCheckBox(
            self.scrollable_checkbox_frame, text=t.get("select_all", "Select All"), variable=self.select_all_var, 
            command=self.toggle_all, font=self.font_main, fg_color=self.accent_color, hover_color=self.accent_hover
        )
        self.cb_select_all.pack(anchor="w", pady=(5, 5), padx=5)

        for plugin_name, version, bat_path, _, size, _ in self.plugins_data:
            self._add_plugin_ui_row(plugin_name, version, bat_path, size)

        self.progress_label = ctk.CTkLabel(self.left_frame, text=t.get("wait", "Waiting..."), font=self.font_main, text_color="#aaaaaa")
        self.progress_label.pack(anchor="w", pady=(5, 0))
        self.progressbar = ctk.CTkProgressBar(self.left_frame, width=left_width, height=16, progress_color=self.accent_color, fg_color="#333333")
        self.progressbar.pack(anchor="w", fill="x", pady=(5, 10)) 
        self.progressbar.set(0)

        self.btn_install = ctk.CTkButton(self.left_frame, text=t.get("install_btn", "Install"), font=self.font_btn, fg_color=self.accent_color, hover_color=self.accent_hover, height=40, command=self.start_installation)
        self.btn_install.pack(anchor="w", fill="x", pady=(0, 5))

        self.force_install_var = ctk.BooleanVar(value=False)
        self.cb_force_install = ctk.CTkCheckBox(
            self.left_frame, text=t.get("force_install", "Force Install"), variable=self.force_install_var,
            font=("Calibri", 12), text_color="#aaaaaa", fg_color=self.accent_color, hover_color=self.accent_hover, 
            checkbox_width=16, checkbox_height=16, border_width=1
        )
        self.cb_force_install.pack(anchor="center", pady=(5, 0))

        self.right_frame = ctk.CTkFrame(master_tab, fg_color="transparent")
        self.right_frame.grid(row=0, column=1, padx=(10, 0), pady=0, sticky="nsew")

        self.right_top_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.right_top_frame.pack(fill="x", pady=(0, 5))
        self.lbl_log = ctk.CTkLabel(self.right_top_frame, text=t.get("log_lbl", "Log"), font=self.font_title)
        self.lbl_log.pack(side="left")
        self.btn_lang = ctk.CTkButton(self.right_top_frame, text="EN" if self.current_lang == "ru" else "RU", font=("Calibri", 13, "bold"), width=35, height=24, fg_color="#333333", hover_color="#444444", command=self.toggle_language)
        self.btn_lang.pack(side="right")

        self.log_container = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.log_container.pack(fill="both", expand=True)
        self.log_textbox = ctk.CTkTextbox(self.log_container, font=("Consolas", 12), fg_color="#151515", text_color="#cccccc", border_width=1, border_color="#333333", corner_radius=8)
        self.log_textbox.pack(fill="both", expand=True)
        self.log_textbox.configure(state="disabled")

        self.target_y = None
        self._is_animating = False
        self.scrollable_checkbox_frame._mouse_wheel_all = self.smooth_wheel_event

    def _add_plugin_ui_row(self, name, version, bat_path, size):
        var = ctk.BooleanVar(value=False)
        custom_color = "#9b59b6" if bat_path == "CUSTOM" else self.accent_color
        custom_hover = "#8e44ad" if bat_path == "CUSTOM" else self.accent_hover
        display_text = self.get_plugin_display_text(name, version, bat_path, size)

        row = ctk.CTkFrame(self.scrollable_checkbox_frame, fg_color="transparent")
        
        cb = ctk.CTkCheckBox(
            row, text=display_text, variable=var, 
            command=lambda n=name, v=var: self.on_plugin_toggle(n, v),
            font=self.font_main, fg_color=custom_color, hover_color=custom_hover, border_width=1,
            checkbox_width=18 if bat_path == "CUSTOM" else 24, checkbox_height=18 if bat_path == "CUSTOM" else 24,
            corner_radius=4 if bat_path == "CUSTOM" else 6
        )
        cb.pack(side="left", pady=3, padx=5)
        
        self.checkboxes.append((name, var))
        self.checkbox_widgets[name] = cb
        self.plugin_rows[name] = row
        row.pack(fill="x")

    def filter_plugins(self, *args):
        query = self.search_var.get().lower()
        
        for name, row in self.plugin_rows.items():
            row.pack_forget()
            
        for name, _ in self.checkboxes:
            cb = self.checkbox_widgets[name]
            if query in name.lower() or query in cb.cget("text").lower():
                self.plugin_rows[name].pack(fill="x")

    def toggle_language(self):
        # Get old names before switching language
        old_lang = "en" if self.current_lang == "ru" else "ru"
        old_t = self.lang_dict.get(old_lang, self.lang_dict["en"])
        old_install_name = old_t.get("tab_install", "Установка")
        old_advanced_name = old_t.get("tab_advanced", "Дополнительно")

        self.current_lang = "en" if self.current_lang == "ru" else "ru"
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
        
        # Update tab names
        new_install_name = t.get("tab_install", "Установка")
        new_advanced_name = t.get("tab_advanced", "Дополнительно")

        if hasattr(self, "view_switcher"):
            self.view_switcher.configure(values=[new_install_name, new_advanced_name])
            
            if self.view_mode_var.get() == old_install_name:
                self.view_mode_var.set(new_install_name)
            elif self.view_mode_var.get() == old_advanced_name:
                self.view_mode_var.set(new_advanced_name)

        self.title(t["title"])
        self.lbl_version.configure(text=t["version_lbl"])
        self.lbl_plugins.configure(text=t["plugins_lbl"])
        self.cb_select_all.configure(text=t["select_all"])
        self.cb_force_install.configure(text=t.get("force_install", "Force Install"))
        self.entry_search.configure(placeholder_text=t.get("search_ph", "Search..."))
        
        if self.progressbar.get() == 0 or self.progressbar.get() == 1.0:
            status_text = t["complete"] if self.progressbar.get() == 1.0 else t["wait"]
            self.progress_label.configure(text=status_text)
            
        self.btn_install.configure(text=t["install_btn"])
        self.lbl_log.configure(text=t["log_lbl"])
        self.btn_clear_log.configure(text=t["clear_log_btn"])
        self.btn_lang.configure(text="RU" if self.current_lang == "en" else "EN")

        if hasattr(self, 'btn_update'): self.btn_update.configure(text=self.update_btn_texts[self.current_lang])

        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        for entry in self.log_history: self.log_textbox.insert("end", entry.get(self.current_lang, entry["en"]) + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

        if hasattr(self, 'advanced_frame'):
            aw = self.advanced_frame
            aw.btn_tab_changelog.configure(text=t["tab_changelog"])
            aw.btn_tab_logs.configure(text=t["tab_logs"])
            aw.btn_tab_custom.configure(text=t["tab_custom"])
            aw.btn_tab_settings.configure(text=t["tab_settings"])
            aw.btn_tab_sync.configure(text=t.get("tab_sync", "Export / Import"))
            aw.btn_tab_uninstall.configure(text=t.get("tab_uninstall", "Uninstall"))
            
            aw.lbl_settings_title.configure(text=t["settings_title"])
            aw.lbl_un_title.configure(text=t.get("un_title", "Uninstall Plugins"))
            aw.lbl_un_desc.configure(text=t.get("un_desc", ""))
            
            if hasattr(aw, 'c_name_var') and not aw.c_name_var.get():
                for child in aw.custom_form_frame.winfo_children():
                    if isinstance(child, ctk.CTkEntry) and child.cget("textvariable") == aw.c_name_var:
                        child.configure(placeholder_text=t["c_name_ph"])

            if hasattr(aw, 'lbl_sync_title'): aw.lbl_sync_title.configure(text=t.get("sync_title"))
            if hasattr(aw, 'lbl_sync_paths'): aw.lbl_sync_paths.configure(text=t.get("sync_paths"))
            if hasattr(aw, 'btn_export_paths'): aw.btn_export_paths.configure(text=t.get("export_btn"))
            if hasattr(aw, 'btn_import_paths'): aw.btn_import_paths.configure(text=t.get("import_btn"))
            if hasattr(aw, 'lbl_sync_custom'): aw.lbl_sync_custom.configure(text=t.get("sync_custom"))
            if hasattr(aw, 'lbl_sync_warn'): aw.lbl_sync_warn.configure(text=t.get("sync_warn"))
            
            if hasattr(aw, 'btn_export'): aw.btn_export.configure(text=t.get("export_log_btn", "Export Logs"))
            if hasattr(aw, 'btn_reset_all'): aw.btn_reset_all.configure(text=t.get("reset_all", "Reset All"))
            
            if aw.frame_custom.winfo_ismapped():
                aw.build_custom_ui()

            aw.changelog_text.configure(state="normal")
            aw.changelog_text.delete("1.0", "end")
            aw.changelog_text.insert("1.0", self.CHANGELOG_TEXT[self.current_lang])
            aw.changelog_text.configure(state="disabled")
            if aw.frame_uninstall.winfo_ismapped(): aw.build_uninstall_ui()

            aw.btn_tab_options.configure(text=t.get("tab_options", "Прочее"))
            if hasattr(aw, 'lbl_drive'): aw.lbl_drive.configure(text=t.get("drive_lbl", "Диск установки AE:"))
            if hasattr(aw, 'lbl_options_title'): aw.lbl_options_title.configure(text=t.get("options_title", "Прочие настройки"))
            if hasattr(aw, 'cb_old_rsmb'): aw.cb_old_rsmb.configure(text=t.get("old_rsmb_lbl", "Старый установщик RSMB"))
            if hasattr(aw, 'cb_rg_plugin_only'): aw.cb_rg_plugin_only.configure(text=t.get("rg_plugin_only_lbl", "Установка и активация плагинов (RedGiant/Universe)"))
            if hasattr(aw, 'cb_rg_maxon_app'): aw.cb_rg_maxon_app.configure(text=t.get("rg_maxon_app_lbl", "Установка Maxon App"))
            if hasattr(aw, 'btn_clear_cache'): aw.btn_clear_cache.configure(text="Очистить кэш (удалить скачанные архивы)" if self.current_lang == "ru" else "Clear download cache")
        if hasattr(self, 'advanced_frame') and hasattr(self.advanced_frame, 'build_sync_ui') and self.advanced_frame.frame_sync.winfo_ismapped(): self.advanced_frame.build_sync_ui()
        
    def log(self, ru_text, en_text=None):
        if en_text is None: en_text = ru_text
        self.after(0, self._safe_log, ru_text, en_text)

    def _safe_log(self, ru_text, en_text=None):
        if en_text is None: en_text = ru_text
        entry = {"ru": ru_text, "en": en_text}
        self.log_history.append(entry)
        self.persistent_log_history.append(entry)
        
        msg = ru_text if self.current_lang == "ru" else en_text
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", msg + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

        if hasattr(self, 'advanced_frame'): self.advanced_frame.append_log(msg + "\n")

    def _update_last_log_line(self, ru_text, en_text=None):
        if en_text is None: en_text = ru_text
        entry = {"ru": ru_text, "en": en_text}
        
        if self.log_history: self.log_history[-1] = entry
        if self.persistent_log_history: self.persistent_log_history[-1] = entry
        
        self.after(0, self._safe_update_last_log_line_ui, ru_text, en_text)

    def _safe_update_last_log_line_ui(self, ru_text, en_text):
        msg = ru_text if self.current_lang == "ru" else en_text
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("end-2c linestart", "end-1c")
        self.log_textbox.insert("end-1c", msg)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

        if hasattr(self, 'advanced_frame'): 
            self.advanced_frame.update_last_log(msg)

    def clear_logs(self):
        self.log_history.clear()
        self.log_textbox.configure(state="normal") 
        self.log_textbox.delete("1.0", "end")        
        self.log_textbox.configure(state="disabled") 

    def extract_version_number(self, text):
        match = re.search(r'\d+(\.\d+)*', text.replace(',', '.'))
        return match.group() if match else "0.0"

    def extract_display_version(self, text):
        match = re.search(r'(?:Beta\s*)?\d+(?:[.,]\d+)*', text, re.IGNORECASE)
        if match:
            found = match.group()
            return "V.Beta " + found[4:].strip() if found.lower().startswith('beta') else "V." + found
        return text

    def is_version_newer(self, latest, current):
        try:
            if "Beta 6.0" in current.lower() or current.lower() == "Beta 6.0":
                return False
                
            v_latest = tuple(map(int, self.extract_version_number(latest).split('.')))
            v_current = tuple(map(int, self.extract_version_number(current).split('.')))
            length = max(len(v_latest), len(v_current))
            return v_latest + (0,) * (length - len(v_latest)) > v_current + (0,) * (length - len(v_current))
        except Exception as e:
            print(f"Version compare error: {e}")
            return False

    def check_for_updates(self):
        def fetch():
            try:
                self.log("[ОБНОВЛЕНИЕ] Подключение к серверам GitHub...", "[UPDATE] Connecting to GitHub servers...")
                url = "https://api.github.com/repos/Aks-iom/Aks-iom-AE-Plugins-install-script/releases/tags/AE"
                req = urllib.request.Request(url, headers={'User-Agent': 'AksiomInstaller'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode())
                    release_name = data.get("name", "") or data.get("tag_name", "")
                    if self.is_version_newer(release_name, self.CURRENT_VERSION):
                        self.after(0, lambda: self.show_update_button(self.extract_display_version(release_name)))
            except Exception as e: 
                print(f"Update check failed: {e}") 
        threading.Thread(target=fetch, daemon=True).start()

    def show_update_button(self, release_title):
        self.update_btn_texts = {"ru": f"Скачать обновление ({release_title})", "en": f"Download update ({release_title})"}
        self.btn_update = ctk.CTkButton(
            self.right_bottom_frame, text=self.update_btn_texts[self.current_lang], font=self.font_main, 
            fg_color=self.accent_color, hover_color=self.accent_hover, height=30, corner_radius=6,
            command=lambda: webbrowser.open("https://github.com/Aks-iom/Aks-iom-AE-Plugins-install-script/releases/tag/AE")
        )
        self.btn_update.pack(side="left", fill="x", expand=True, padx=(0, 10))

    def smooth_wheel_event(self, event):
        if not self.scrollable_checkbox_frame._check_if_mouse_inside(event.x_root, event.y_root): return
        canvas = self.scrollable_checkbox_frame._parent_canvas
        top, bottom = canvas.yview()
        if top == 0.0 and bottom == 1.0: return
        self.target_y = max(0.0, min(1.0, (self.target_y or top) + (-1 if event.delta > 0 else 1) * 0.06))
        if not self._is_animating:
            self._is_animating = True
            self.animate_scroll(canvas)

    def animate_scroll(self, canvas):
        current_y = canvas.yview()[0]
        if self.target_y is not None:
            diff = self.target_y - current_y
            if abs(diff) > 0.001:
                canvas.yview_moveto(current_y + diff * 0.25)
                self.after(16, self.animate_scroll, canvas)
            else:
                canvas.yview_moveto(self.target_y)
                self.target_y = None
                self._is_animating = False

    def get_search_dirs(self, ae_version):
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
            os.path.join(pd, "Red Giant")
        ]
        plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)
        if os.path.exists(plugins_dir): dirs.append(plugins_dir)
        if os.path.exists(scripts_dir): dirs.append(scripts_dir)
        return dirs

    def _has_relevant_files(self, directory):
        try:
            for root, _, files in os.walk(directory):
                for file in files:
                    if file.lower().endswith(('.aex', '.jsx', '.jsxbin', '.dll', '.exe', '.prm', '.lic', '.zxp', '.plugin')):
                        return True
        except (PermissionError, OSError): pass
        return False

    def _fast_search(self, directory, plugin_name, keywords, max_depth=4, current_depth=0):
        if current_depth > max_depth: return False
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    name_lower = entry.name.lower()
                    
                    match_found = any(kw.lower() in name_lower for kw in keywords)
                    if plugin_name == "Deep_Glow" and "2" in name_lower and "deep" in name_lower:
                        match_found = False

                    if match_found:
                        if entry.is_file() and name_lower.endswith(('.aex', '.jsx', '.jsxbin', '.dll', '.exe', '.prm', '.lic', '.zxp')):
                            return True
                        elif entry.is_dir():
                            if self._has_relevant_files(entry.path):
                                return True

                    if entry.is_dir():
                        if self._fast_search(entry.path, plugin_name, keywords, max_depth, current_depth + 1):
                            return True
        except (PermissionError, OSError): pass
        return False

    def is_plugin_installed(self, plugin_name, ae_version):
        search_dirs = []
        has_custom = False
        
        custom_main_path = self.custom_plugin_paths.get(plugin_name, "").strip()
        if custom_main_path:
            search_dirs.append(self.resolve_target_path(plugin_name, "", ae_version))
            has_custom = True
            
        if plugin_name in self.custom_data:
            c_files = self.custom_data[plugin_name].get("custom_files", {})
            plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)
            custom_install_path = self.custom_install_path_var.get().strip()
            
            # Подменяем версию в глобальном пути, если он задан
            if custom_install_path and ae_version != "None":
                custom_install_path = re.sub(r'(?i)(After Effects\s*)20\d{2}', rf'\g<1>{ae_version}', custom_install_path)

            for t_id, p in c_files.items():
                target_path = p.get("target_path", "")
                
                # Подменяем версию в индивидуальном пути плагина
                if target_path and ae_version != "None":
                    target_path = re.sub(r'(?i)(After Effects\s*)20\d{2}', rf'\g<1>{ae_version}', target_path)
                
                if target_path:
                    search_dirs.append(target_path)
                    has_custom = True
                
                # Точная проверка для формата 'file' (ищем конкретный файл)
                if t_id == "file":
                    dest_dir = target_path if target_path else plugins_dir
                    filename = p.get("filename", "")
                    if filename and os.path.exists(os.path.join(dest_dir, filename)):
                        return True
                        
                # Точная проверка для формата 'zip' (проверяем, создалась ли папка с плагином и есть ли в ней файлы)
                if t_id == "zip":
                    extract_target = target_path if target_path else (custom_install_path if custom_install_path else os.path.join(plugins_dir, plugin_name))
                    if os.path.exists(extract_target) and os.path.basename(extract_target).lower() == plugin_name.lower():
                        try:
                            if any(os.scandir(extract_target)):
                                return True
                        except OSError:
                            pass
                    
        if not has_custom: search_dirs = self.get_search_dirs(ae_version)
        keywords = self.plugin_keywords.get(plugin_name, [plugin_name.lower()])
        
        for d in set(d for d in search_dirs if os.path.exists(d)):
            if self._fast_search(d, plugin_name, keywords): return True
            
        pd = os.environ.get("ProgramData", r"C:\ProgramData")
        
        if not has_custom and plugin_name == "Sapphire" and glob.glob(os.path.join(pd, "GenArts", "rlm", "*.lic")): 
            return True
            
        return False
    
    def check_installed_plugins(self):
        ae_ver = self.version_var.get()
        threading.Thread(target=self._async_check_installed, args=("20" + ae_ver if ae_ver != "None" else "None",), daemon=True).start()

    def _async_check_installed(self, full_ver):
        results = {name: self.is_plugin_installed(name, full_ver) if full_ver != "None" else False for name, _ in self.checkboxes}
        self.after(0, lambda: [self.checkbox_widgets[n].configure(text_color="#4CAF50" if r else "#cccccc") for n, r in results.items() if n in self.checkbox_widgets])

    def toggle_all(self):
        state = self.select_all_var.get()
        for _, var in self.checkboxes: var.set(state)
        
        if state:
            ru_msg = self.lang_dict.get("ru", {}).get("rsmb_warn", "Мне не удалось сделать всю установку автоматически, поэтому вам придется нажать Extract самому (RSMB).")
            en_msg = self.lang_dict.get("en", {}).get("rsmb_warn", "I could not automate the whole installation, so you will have to click Extract yourself (RSMB).")
            self.log(f"⚠️ [ВНИМАНИЕ] {ru_msg}", f"⚠️ [WARNING] {en_msg}")
            
            popups = []
            for name, _ in self.checkboxes:
                if name in self.custom_data:
                    w_text = self.custom_data[name].get("warning_text", "").strip()
                    w_popup = self.custom_data[name].get("warning_popup", False)
                    if w_text:
                        self.log(f"⚠️ [ВНИМАНИЕ - {name}] {w_text}", f"⚠️ [WARNING - {name}] {w_text}")
                        if w_popup:
                            popups.append(f"{name}:\n{w_text}")
                            
            if popups:
                t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
                messagebox.showwarning(t.get("warn_title", "Внимание"), "\n\n".join(popups))

    def on_plugin_toggle(self, plugin_name, var):
        self.select_all_var.set(all(var.get() for _, var in self.checkboxes))
        
        if var.get():
            if plugin_name == "RSMB":
                ru_msg = self.lang_dict.get("ru", {}).get("rsmb_warn", "Мне не удалось сделать всю установку автоматически, поэтому вам придется нажать Extract самому (RSMB).")
                en_msg = self.lang_dict.get("en", {}).get("rsmb_warn", "I could not automate the whole installation, so you will have to click Extract yourself (RSMB).")
                self.log(f"⚠️ [ВНИМАНИЕ] {ru_msg}", f"⚠️ [WARNING] {en_msg}")
                
            if plugin_name in self.custom_data:
                w_text = self.custom_data[plugin_name].get("warning_text", "").strip()
                w_popup = self.custom_data[plugin_name].get("warning_popup", False)
                if w_text:
                    self.log(f"⚠️ [ВНИМАНИЕ - {plugin_name}] {w_text}", f"⚠️ [WARNING - {plugin_name}] {w_text}")
                    if w_popup:
                        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
                        messagebox.showwarning(t.get("warn_title", "Внимание"), w_text)

    def _update_progress_ui(self, text, value):
        self.progress_label.configure(text=text)
        self.progressbar.set(value)

    def verify_archive_integrity(self, zip_path, expected_md5=None):
        if expected_md5:
            hash_md5 = hashlib.md5()
            with open(zip_path, "rb") as f:
                for chunk in iter(lambda: f.read(1048576), b""): 
                    hash_md5.update(chunk)
            if hash_md5.hexdigest() != expected_md5: return False
        try:
            with zipfile.ZipFile(zip_path, 'r') as z: return not z.testzip()
        except zipfile.BadZipFile: 
            return False
        except OSError as e:
            print(f"File system error checking archive integrity: {e}")
            return False

    def download_from_gdrive(self, file_id, destination_path, plugin_name="Plugin", current_index=0, total_plugins=1):
        if not file_id: return False
        try:
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            self.log(f"[*] Запуск загрузки {plugin_name} (Google Drive через gdown)...", f"[*] Starting download {plugin_name} (Google Drive via gdown)...")

            original_stderr = sys.stderr
            catcher = GdownLogCatcher(self, original_stderr, current_index, total_plugins, plugin_name)
            sys.stderr = catcher

            try:
                gdown.download(id=file_id, output=destination_path, quiet=False)
            finally:
                sys.stderr = original_stderr

            if os.path.exists(destination_path):
                self.log(f"[+] Файл {plugin_name} успешно скачан.", f"[+] File {plugin_name} successfully downloaded.")
                return True
            else:
                self.log(f"❌ Ошибка скачивания {plugin_name}: файл не был создан.", f"❌ Error downloading {plugin_name}: file was not created.")
                return False

        except Exception as e:
            self.log(f"❌ Системная ошибка при скачивании {plugin_name}: {e}", f"❌ System Error during download of {plugin_name}: {e}")
            return False

    def start_installation(self):
        self.clear_logs()
        ae_version = self.version_var.get()
        if ae_version == "None":
            self.log("[ОШИБКА] Выберите версию After Effects!", "[ERROR] Please select an After Effects version!")
            return

        full_ae_version = "20" + ae_version
        
        force_install = self.force_install_var.get()
        selected = []
        
        for name, var in self.checkboxes:
            if var.get():
                if force_install or not self.is_plugin_installed(name, full_ae_version):
                    selected.append(name)
                else:
                 self.log(f"Пропуск: Плагин {name} уже установлен.", f"Skipped: Plugin {name} is already installed.")

        if not selected: 
            self.log("Нет плагинов для установки или они уже установлены.", "No plugins to install or already installed.")
            return

        self.btn_install.configure(state="disabled")
        self.log(
            f"\n{'='*50}\n🚀 УСТАНОВКА AFTER EFFECTS {full_ae_version}\n{'='*50}",
            f"\n{'='*50}\n🚀 INSTALLING AFTER EFFECTS {full_ae_version}\n{'='*50}"
        )

        custom_install_path = self.custom_install_path_var.get().strip()
        threading.Thread(target=self.run_install_process, args=(full_ae_version, selected, custom_install_path), daemon=True).start()

    def execute_native_install(self, plugin_name, ae_version, src_dir):
        plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)
        pf = self.get_pf()
        pf86 = self.get_pf86()
        pd = os.environ.get("ProgramData", r"C:\ProgramData")

        if plugin_name == "BCC":
            subprocess.run([os.path.join(src_dir, "BCC_Setup.exe"), "/s", "/v/qb", "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True, creationflags=CREATE_NO_WINDOW)
            bcc_lib = os.path.join(pf, "BorisFX", "ContinuumAE", "14", "lib")
            os.makedirs(bcc_lib, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Crack", "Continuum_Common_AE.dll"), bcc_lib)
            shutil.copytree(os.path.join(src_dir, "Crack", "GenArts"), os.path.join(pd, "GenArts"), dirs_exist_ok=True)
            
        elif plugin_name == "Bokeh":
            dest = self.resolve_target_path(plugin_name, os.path.join(plugins_dir, "Plugins Everything"), ae_version)
            os.makedirs(dest, exist_ok=True); shutil.copy2(os.path.join(src_dir, "Bokeh.aex"), dest)
            
        elif plugin_name == "Deep_Glow":
            dest = self.resolve_target_path(plugin_name, os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore"), ae_version)
            os.makedirs(dest, exist_ok=True); shutil.copy2(os.path.join(src_dir, "Deep Glow.aex"), dest)
            
        elif plugin_name == "Deep_Glow2":
            dest = self.resolve_target_path(plugin_name, os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore"), ae_version)
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "DeepGlow2.aex"), dest); shutil.copy2(os.path.join(src_dir, "IrisBlurSDK.dll"), dest)
            
        elif plugin_name == "Element":
            dest_plugin = self.resolve_target_path(plugin_name, os.path.join(plugins_dir, "VideoCopilot"), ae_version)
            dest_lic = os.path.join(pd, "VideoCopilot")
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH); ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
            dest_docs = os.path.join(buf.value, "VideoCopilot")
            os.makedirs(dest_plugin, exist_ok=True); os.makedirs(dest_lic, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Element.aex"), dest_plugin); shutil.copy2(os.path.join(src_dir, "element2_license"), dest_lic)
            shutil.copytree(os.path.join(src_dir, "VideoCopilot"), dest_docs, dirs_exist_ok=True)
            
        elif plugin_name == "Fast_Layers":
            dest = self.resolve_target_path(plugin_name, scripts_dir, ae_version)
            os.makedirs(dest, exist_ok=True); shutil.copy2(os.path.join(src_dir, "Fast_Layers.jsx"), dest)
            
        elif plugin_name == "Flow":
            dest = self.resolve_target_path(plugin_name, os.path.join(pf86, "Common Files", "Adobe", "CEP", "extensions", "flow"), ae_version)
            src_flow = os.path.join(src_dir, "flow-v1.5.2")
            if os.path.exists(src_flow): shutil.copytree(src_flow, dest, dirs_exist_ok=True)
            
            for csxs in ["CSXS.10", "CSXS.11", "CSXS.12", "CSXS.13", "CSXS.14", "CSXS.15", "CSXS.16"]:
                try:
                    access = winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
                    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, rf"Software\Adobe\{csxs}", 0, access) as key:
                        winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
                except OSError as e: 
                    print(f"Error modifying HKLM registry for CEP: {e}")
                
        elif plugin_name in ["Fxconsole", "Glitchify", "Saber"]:
            dest = self.resolve_target_path(plugin_name, os.path.join(plugins_dir, "VideoCopilot"), ae_version)
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, f"{'FXConsole' if plugin_name == 'Fxconsole' else plugin_name}.aex"), dest)
            
        elif plugin_name == "Mocha_Pro":
            subprocess.run([os.path.join(src_dir, "mochapro_2026.0.1_adobe_installer.exe"), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True, creationflags=CREATE_NO_WINDOW)
            time.sleep(4)
            subprocess.run(["taskkill", "/F", "/IM", "mochapro.exe", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        
        elif plugin_name == "Influx":
            dest = self.resolve_target_path(plugin_name, os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore", "Autokroma Influx"), ae_version)
            os.makedirs(dest, exist_ok=True)
            src_influx = os.path.join(src_dir, "Autokroma Influx")
            if os.path.exists(src_influx):
                shutil.copytree(src_influx, dest, dirs_exist_ok=True)
            else:
                shutil.copytree(src_dir, dest, dirs_exist_ok=True)
            
        elif plugin_name == "RSMB":
            if self.old_rsmb_var.get():
                dest = self.resolve_target_path(plugin_name, os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore", "RSMB"), ae_version)
                os.makedirs(dest, exist_ok=True)
                for aex in glob.glob(os.path.join(src_dir, "*.aex")):
                    shutil.copy2(aex, dest)
            else:
                exe_files = glob.glob(os.path.join(src_dir, "*.exe"))
                if exe_files:
                    installer_path = exe_files[0]
                    self.log("[*] Запуск установщика RSMB. Пожалуйста, пройдите установку в появившемся окне...", "[*] Starting RSMB installer. Please complete the setup in the window...")
                    subprocess.run([installer_path], check=True)
                else:
                    raise FileNotFoundError(f"Установочный .exe файл для RSMB не найден в {src_dir}")
            
        elif plugin_name == "Sapphire":
            try: subprocess.run([os.path.join(src_dir, "sapphire_ae_install.exe"), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True, creationflags=CREATE_NO_WINDOW)
            except subprocess.CalledProcessError as e:
                if e.returncode != 3010: raise e
                
        elif plugin_name == "Shake_Generator":
            dest = self.resolve_target_path(plugin_name, scripts_dir, ae_version)
            os.makedirs(dest, exist_ok=True)
            for jsx in glob.glob(os.path.join(src_dir, "*.jsx")): shutil.copy2(jsx, dest)
            
        elif plugin_name == "Textevo2":
            dest = self.resolve_target_path(plugin_name, scripts_dir, ae_version)
            os.makedirs(dest, exist_ok=True)
            for jsxbin in glob.glob(os.path.join(src_dir, "*.jsxbin")): shutil.copy2(jsxbin, dest)
            
        elif plugin_name == "Twich":
            dest = self.resolve_target_path(plugin_name, os.path.join(plugins_dir, "VideoCopilot"), ae_version)
            os.makedirs(dest, exist_ok=True)
            for aex in glob.glob(os.path.join(src_dir, "*.aex")): shutil.copy2(aex, dest)
            for key_file in glob.glob(os.path.join(src_dir, "*.key")): shutil.copy2(key_file, dest)
            
        elif plugin_name == "Twixtor":
            dest = self.resolve_target_path(plugin_name, os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore", "Twixtor8AE"), ae_version)
            os.makedirs(dest, exist_ok=True)
            src_twixtor = os.path.join(src_dir, "Twixtor8AE")
            if os.path.exists(src_twixtor): shutil.copytree(src_twixtor, dest, dirs_exist_ok=True)
            
        elif plugin_name == "Uwu2x":
            cep_base = self.resolve_target_path(plugin_name, os.path.join(pf86, "Common Files", "Adobe", "CEP", "extensions"), ae_version)
            os.makedirs(cep_base, exist_ok=True)
            src_pro, src_norm = os.path.join(src_dir, "uwu2x-pro"), os.path.join(src_dir, "uwu2x")
            if os.path.exists(src_pro): shutil.copytree(src_pro, os.path.join(cep_base, "uwu2x-pro"), dirs_exist_ok=True)
            elif os.path.exists(src_norm): shutil.copytree(src_norm, os.path.join(cep_base, "uwu2x"), dirs_exist_ok=True)
            
            for csxs in ["CSXS.10", "CSXS.11", "CSXS.12", "CSXS.13", "CSXS.14", "CSXS.15", "CSXS.16"]:
                try:
                    access = winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
                    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, rf"Software\Adobe\{csxs}", 0, access) as key:
                        winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
                except OSError as e: 
                    print(f"Error modifying HKLM registry for CEP: {e}")
                
        elif plugin_name == "Prime_tool":
            cep_path = self.resolve_target_path(plugin_name, os.path.join(pf86, "Common Files", "Adobe", "CEP", "extensions", "com.PrimeTools"), ae_version)
            os.makedirs(cep_path, exist_ok=True)
            zxp_file = os.path.join(src_dir, "com.PrimeTools.cep.zxp")
            if os.path.exists(zxp_file):
                with zipfile.ZipFile(zxp_file, 'r') as zip_ref: zip_ref.extractall(cep_path)
                
        elif plugin_name in ["RedGiant", "Universe"]:
            if self.rg_maxon_app_var.get():
                maxon_installer = os.path.join(src_dir, "1_Maxon.exe")
                if os.path.exists(maxon_installer):
                    subprocess.run([maxon_installer, "--mode", "unattended", "--unattendedmodeui", "minimal"], check=True, creationflags=CREATE_NO_WINDOW)
            
            if self.rg_plugin_only_var.get():
                rg_installer = os.path.join(src_dir, "2_RedGiant.exe")
                unlocker = os.path.join(src_dir, "3_Unlocker.exe")
                if os.path.exists(rg_installer): subprocess.run([rg_installer, "--mode", "unattended", "--unattendedmodeui", "minimal"], check=True, creationflags=CREATE_NO_WINDOW)
                if os.path.exists(unlocker): subprocess.run([unlocker, "/SILENT"], check=True, creationflags=CREATE_NO_WINDOW)
                
            time.sleep(6)
            subprocess.run(["taskkill", "/F", "/IM", "Maxon App.exe", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)

    def _fix_russian_hotkeys(self):
        self.bind_all("<Key>", lambda e: self._handle_russian_hotkeys(e))

    def _handle_russian_hotkeys(self, event):
        if event.state & 4:
            widget = self.focus_get()
            if not widget: return
            try:
                if event.keycode == 65:
                    if hasattr(widget, 'select_range'): widget.select_range(0, 'end'); widget.icursor('end'); return "break"
                    elif hasattr(widget, 'tag_add'): widget.tag_add('sel', '1.0', 'end'); return "break"
                elif event.keycode == 67: widget.event_generate("<<Copy>>"); return "break"
                elif event.keycode == 86: widget.event_generate("<<Paste>>"); return "break"
                elif event.keycode == 88: widget.event_generate("<<Cut>>"); return "break"
                elif event.keycode == 90: widget.event_generate("<<Undo>>"); return "break"
            except Exception as e:
                print(f"Hotkey event handling error: {e}")

    def uninstall_plugin(self, plugin_name, ae_version):
        exe_installers = ["BCC", "Mocha_Pro", "Sapphire", "RedGiant"]
        
        # Блокируем автоматическое удаление RSMB только если он устанавливался через .exe
        if plugin_name == "RSMB" and not self.old_rsmb_var.get():
            exe_installers.append("RSMB")
            
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
        
        if plugin_name in exe_installers:
            messagebox.showwarning(t.get("warn_title", "Warning"), t.get("un_warn_exe", "Uninstall this using Windows Control Panel."))
            return False
        # ... дальше твой код

        try:
            search_dirs = []
            deleted_something = False
            
            custom_main_path = self.custom_plugin_paths.get(plugin_name, "").strip()
            if custom_main_path: 
                search_dirs.append(self.resolve_target_path(plugin_name, "", ae_version))
                
            if plugin_name in self.custom_data:
                c_files = self.custom_data[plugin_name].get("custom_files", {})
                plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)
                custom_install_path = self.custom_install_path_var.get().strip()

                if custom_install_path and ae_version != "None":
                    custom_install_path = re.sub(r'(?i)(After Effects\s*)20\d{2}', rf'\g<1>{ae_version}', custom_install_path)

                for t_id, f_info in c_files.items():
                    target_dir = f_info.get("target_path", "")
                    
                    # Динамическая замена версии AE при удалении
                    if target_dir and ae_version != "None":
                        target_dir = re.sub(r'(?i)(After Effects\s*)20\d{2}', rf'\g<1>{ae_version}', target_dir)
                    
                    if not target_dir:
                        if t_id == "zip":
                            target_dir = custom_install_path if custom_install_path else os.path.join(plugins_dir, plugin_name)
                        elif t_id in ["exe", "file"]:
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
                            if os.path.isdir(full_path): shutil.rmtree(full_path, ignore_errors=True)
                            else: os.remove(full_path)
                            deleted_something = True
            
            search_dirs.extend(self.get_search_dirs(ae_version))
                
            keywords = self.plugin_keywords.get(plugin_name, [plugin_name.lower()])

            for d in set(d for d in search_dirs if os.path.exists(d)):
                try:
                    with os.scandir(d) as it:
                        for entry in it:
                            name_lower = entry.name.lower()
                            
                            match_found = False
                            for kw in keywords:
                                if kw.lower() in name_lower:
                                    match_found = True
                                    break
                                    
                            if match_found:
                                if plugin_name == "Deep_Glow" and "2" in name_lower and "deep" in name_lower: continue
                                if entry.is_dir(): shutil.rmtree(entry.path, ignore_errors=True)
                                else: os.remove(entry.path)
                                deleted_something = True
                except (PermissionError, OSError) as e:
                     print(f"Error accessing directory while uninstalling: {e}")

            return deleted_something

        except Exception as e:
            self.log(f"Ошибка при удалении {plugin_name}: {e}", f"Error uninstalling {plugin_name}: {e}")
            return False
        
    def _ensure_downloaded(self, plugin_name, index, total):
        plugin_info = next((p for p in self.plugins_data if p[0] == plugin_name), None)
        if not plugin_info: return False
        
        _, _, bat_path, needs_version, _, expected_md5 = plugin_info
        is_custom = plugin_name in self.custom_data
        success = True
        
        if is_custom:
            c_files = self.custom_data[plugin_name].get("custom_files", {})
            for t_id, f_info in c_files.items():
                c_source, c_filename = f_info.get("source"), f_info.get("filename")
                target_file_path = os.path.join(self.base_dir, c_filename)
                if c_source == "gdrive" and not os.path.exists(target_file_path):
                    if not self.download_from_gdrive(f_info.get("gdrive_id"), target_file_path, plugin_name, index, total):
                        success = False
                if not os.path.exists(target_file_path): success = False
        else:
            plugin_src_dir = os.path.dirname(os.path.join(self.base_dir, bat_path))
            zip_path = os.path.join(self.base_dir, f"{plugin_name}.zip")
            
            if not os.path.exists(plugin_src_dir):
                if not os.path.exists(zip_path) or not self.verify_archive_integrity(zip_path, expected_md5):
                    if not self.download_from_gdrive(self.gdrive_file_ids.get(plugin_name), zip_path, plugin_name, index, total):
                        success = False
                
                if success and os.path.exists(zip_path) and self.verify_archive_integrity(zip_path, expected_md5):
                    self.log(f"[*] Распаковка {plugin_name}...", f"[*] Extracting {plugin_name}...")
                    try:
                        with zipfile.ZipFile(zip_path, 'r') as zip_ref: zip_ref.extractall(self.base_dir)
                    except Exception as e:
                        self.log(f"❌ Ошибка распаковки {plugin_name}: {e}")
                        success = False
                    finally:
                        try: os.remove(zip_path)
                        except OSError: pass
                elif not os.path.exists(plugin_src_dir):
                    success = False
        return success

    def _perform_installation(self, plugin_name, index, total, ae_version, custom_install_path):
        plugin_info = next((p for p in self.plugins_data if p[0] == plugin_name), None)
        if not plugin_info: return
        _, _, bat_path, needs_version, _, expected_md5 = plugin_info
        is_custom = plugin_name in self.custom_data
        native_plugins = [p[0] for p in self.plugins_data]

        # Применяем замену версии к глобальному custom пути
        if custom_install_path and ae_version != "None":
            custom_install_path = re.sub(r'(?i)(After Effects\s*)20\d{2}', rf'\g<1>{ae_version}', custom_install_path)

        if is_custom:
            c_files = self.custom_data[plugin_name].get("custom_files", {})
            plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)

            for t_id, f_info in c_files.items():
                c_filename = f_info.get("filename")
                target_file_path = os.path.join(self.base_dir, c_filename)
                c_target_path = f_info.get("target_path", "")

                # Динамическая замена версии AE в пути копирования/распаковки
                if c_target_path and ae_version != "None":
                    c_target_path = re.sub(r'(?i)(After Effects\s*)20\d{2}', rf'\g<1>{ae_version}', c_target_path)

                try:
                    if t_id == "zip":
                        self.log("[*] Распаковка .zip...", "[*] Extracting .zip...")
                        extract_target = c_target_path if c_target_path else (custom_install_path if custom_install_path else os.path.join(plugins_dir, plugin_name))
                        os.makedirs(extract_target, exist_ok=True)
                        with zipfile.ZipFile(target_file_path, 'r') as zip_ref: zip_ref.extractall(extract_target)
                    elif t_id == "exe": 
                        self.log("[*] Запуск установщика .exe...", "[*] Running .exe installer...")
                        subprocess.run([target_file_path], check=True)
                    elif t_id == "file":
                        self.log("[*] Копирование файла...", "[*] Copying file...")
                        target_dir = c_target_path if c_target_path else plugins_dir
                        os.makedirs(target_dir, exist_ok=True); shutil.copy2(target_file_path, target_dir)
                    elif t_id == "reg":
                        self.log("[*] Применение файла реестра...", "[*] Applying registry file...")
                        ctypes.windll.shell32.ShellExecuteW(None, "runas", "reg.exe", f'import "{target_file_path}"', None, 0)
                        time.sleep(1) 
                    self.log(f"✅ Файл .{t_id} успешно установлен.", f"✅ .{t_id} file successfully installed.")
                except Exception as e:
                    self.log(f"❌ Непредвиденная ошибка при установке {t_id}: {e}", f"❌ Unexpected error installing {t_id}: {e}")
        else:
            # Восстановленный код для стандартных плагинов
            plugin_src_dir = os.path.dirname(os.path.join(self.base_dir, bat_path))
            self.log(f"[*] Выполнение установки {plugin_name}...", f"[*] Executing setup for {plugin_name}...")
            try:
                self.execute_native_install(plugin_name, ae_version, plugin_src_dir)
            except Exception as e:
                self.log(f"❌ Ошибка установки {plugin_name}: {e}")

    def run_install_process(self, ae_version, selected_plugins, custom_install_path):
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
        try:
            total = len(selected_plugins)
            download_events = {name: threading.Event() for name in selected_plugins}
            download_results = {name: False for name in selected_plugins}
            
            def download_task(name, idx):
                try:
                    res = self._ensure_downloaded(name, idx, total)
                    download_results[name] = res
                except Exception as e:
                    self.log(f"❌ Ошибка фоновой загрузки {name}: {e}")
                    download_results[name] = False
                finally:
                    download_events[name].set()

            if selected_plugins:
                threading.Thread(target=download_task, args=(selected_plugins[0], 0), daemon=True).start()
            
            for index, plugin_name in enumerate(selected_plugins):
                self.after(0, self._update_progress_ui, f"({index+1}/{total}) {t.get('wait', 'Ожидание')}: {plugin_name}...", index / total)
                
                download_events[plugin_name].wait()
                
                if index + 1 < total:
                    next_plugin = selected_plugins[index + 1]
                    threading.Thread(target=download_task, args=(next_plugin, index + 1), daemon=True).start()
                
                if not download_results[plugin_name]:
                    self.log(f"❌ Пропуск установки {plugin_name} из-за ошибки загрузки.", f"❌ Skipping {plugin_name} installation due to download error.")
                    continue
                
                self.after(0, self._update_progress_ui, f"({index+1}/{total}) {t.get('installing', 'Установка')}: {plugin_name}...", (index + 0.5) / total)
                self.log(
                    f"\n----------------------------------------\n📦 ПЛАГИН: {plugin_name}\n----------------------------------------",
                    f"\n----------------------------------------\n📦 PLUGIN: {plugin_name}\n----------------------------------------"
                )

                self._perform_installation(plugin_name, index, total, ae_version, custom_install_path)
                self.after(0, self._update_progress_ui, f"({index+1}/{total}) {t.get('complete', 'Готово')}: {plugin_name}", (index + 1) / total)

            self.log(f"\n{'='*50}\n🔍 ФИНАЛЬНАЯ ПРОВЕРКА...\n{'='*50}", f"\n{'='*50}\n🔍 FINAL CHECK...\n{'='*50}")
            for plugin_name in selected_plugins:
                if not self.is_plugin_installed(plugin_name, ae_version):
                    self.log(f"❌ [ОШИБКА] Плагин {plugin_name} не найден после установки!", f"❌ [ERROR] Plugin {plugin_name} not found after installation!")
                else:
                    self.log(f"✅ {plugin_name} прошел проверку.", f"✅ {plugin_name} passed the check.")

        except Exception as e: 
            self.log(f"\n[КРИТИЧЕСКАЯ ОШИБКА] Общий сбой процесса установки: {e}", f"\n[CRITICAL ERROR] General installation process failure: {e}")
        finally: 
            self.after(0, lambda: [self.progress_label.configure(text=t.get("complete", "Complete")), self.progressbar.set(1.0), self.check_installed_plugins(), self.btn_install.configure(state="normal")])

def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception: return False

if __name__ == "__main__":
    if is_admin():
        app = AksiomInstaller()
        app.mainloop()
    else:
        params = " ".join([f'"{arg}"' for arg in sys.argv[1:]]) if getattr(sys, 'frozen', False) else f'"{os.path.abspath(__file__)}" ' + " ".join([f'"{arg}"' for arg in sys.argv[1:]])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        sys.exit()