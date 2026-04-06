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
from tkinter import END, messagebox, filedialog
import shutil
import winreg
import time
import ctypes
import ctypes.wintypes
import hashlib

# Флаг для скрытия окон консоли при вызове subprocess (только для Windows)
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# =================================================================
# КЛАСС-ПЕРЕХВАТЧИК ДЛЯ ПОЛУЧЕНИЯ ПРОГРЕССА СКАЧИВАНИЯ
# =================================================================
class GdownLogCatcher:
    def __init__(self, ui_app, original_stderr):
        self.ui_app = ui_app
        self.original_stderr = original_stderr
        self.is_progress = False
        self.last_update = 0  

    def write(self, text):
        if self.original_stderr:
            self.original_stderr.write(text)
            self.original_stderr.flush()

        if not text:
            return

        if '\r' in text:
            clean_text = text.split('\r')[-1].strip()
            if clean_text:
                current_time = time.time()
                if current_time - self.last_update > 0.1:
                    if not self.is_progress:
                        self.ui_app.after(0, self.ui_app._gdown_log, clean_text)
                        self.is_progress = True
                    else:
                        self.ui_app.after(0, self.ui_app._update_last_log_line, clean_text)
                    self.last_update = current_time
        else:
            clean_text = text.strip()
            if clean_text:
                if self.is_progress:
                    self.is_progress = False
                self.ui_app.after(0, self.ui_app._gdown_log, clean_text)

    def flush(self):
        if self.original_stderr:
            self.original_stderr.flush()

    def isatty(self):
        return True

ctk.set_appearance_mode("dark")

# =================================================================
# ДОПОЛНИТЕЛЬНОЕ ОКНО (ВКЛАДКИ СБОКУ)
# =================================================================
class AdvancedWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        
        t = self.master.lang_dict[self.master.current_lang]
        self.title(t["advanced_btn"])
        self.geometry("780x660")
        self.minsize(750, 600)
        
        # Окно поверх ТОЛЬКО основного окна приложения (не ломая цвет верхней панели)
        self.transient(self.master)
        
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        
        # === БОКОВОЕ МЕНЮ ===
        self.sidebar_frame = ctk.CTkFrame(self, width=180, corner_radius=0, fg_color="#1a1a1a")
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)

        self.btn_tab_changelog = ctk.CTkButton(
            self.sidebar_frame, text=t["tab_changelog"], font=self.master.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_changelog
        )
        self.btn_tab_changelog.pack(pady=(20, 5), padx=10, fill="x")

        self.btn_tab_logs = ctk.CTkButton(
            self.sidebar_frame, text=t["tab_logs"], font=self.master.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_logs
        )
        self.btn_tab_logs.pack(pady=5, padx=10, fill="x")

        self.btn_tab_custom = ctk.CTkButton(
            self.sidebar_frame, text=t["tab_custom"], font=self.master.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_custom
        )
        self.btn_tab_custom.pack(pady=5, padx=10, fill="x")

        self.btn_tab_settings = ctk.CTkButton(
            self.sidebar_frame, text=t["tab_settings"], font=self.master.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_settings
        )
        self.btn_tab_settings.pack(pady=5, padx=10, fill="x")
        
        # --- ДОБАВЛЕНА КНОПКА ЭКСПОРТА/ИМПОРТА ---
        btn_sync_text = "Экспорт / Импорт" if self.master.current_lang == "ru" else "Export / Import"
        self.btn_tab_sync = ctk.CTkButton(
            self.sidebar_frame, text=btn_sync_text, font=self.master.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_sync
        )
        self.btn_tab_sync.pack(pady=5, padx=10, fill="x")
        # -----------------------------------------

       # === ФРЕЙМЫ КОНТЕНТА ===
        self.frame_changelog = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_logs = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_custom = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.frame_settings = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_sync = ctk.CTkFrame(self, fg_color="transparent") # <--- ДОБАВЛЕНО

        # --- Наполнение Changelog ---
        self.changelog_text = ctk.CTkTextbox(
            self.frame_changelog, font=("Calibri", 14), fg_color="#151515", 
            text_color="#bbbbbb", wrap="word", corner_radius=8
        )
        self.changelog_text.pack(fill="both", expand=True, padx=20, pady=20)
        self.changelog_text.insert("1.0", self.master.CHANGELOG_TEXT[self.master.current_lang])
        self.changelog_text.configure(state="disabled")

        # --- Наполнение Logs ---
        self.log_textbox = ctk.CTkTextbox(
            self.frame_logs, font=("Consolas", 12), fg_color="#151515", 
            text_color="#cccccc", wrap="word", corner_radius=8
        )
        self.log_textbox.pack(fill="both", expand=True, padx=20, pady=(20, 10))
        
        self.btn_export = ctk.CTkButton(
            self.frame_logs, text=t["export_log_btn"], font=self.master.font_main, 
            fg_color="#333333", hover_color="#444444", height=35, corner_radius=6, 
            command=self.export_persistent_logs
        )
        self.btn_export.pack(side="right", padx=20, pady=(0, 20))

        # --- ЗАМЕНИТЬ Наполнение Settings ---
        self.frame_settings.grid_columnconfigure(0, weight=1)
        
        # ТЕПЕРЬ СТРОКА 1 отвечает за расширение скролл-фрейма (освобождаем место)
        self.frame_settings.grid_rowconfigure(1, weight=1) 
        
        # Заголовок (по центру)
        self.lbl_settings_title = ctk.CTkLabel(self.frame_settings, text=t["settings_title"], font=self.master.font_title)
        self.lbl_settings_title.grid(row=0, column=0, pady=(30, 20))

        # --- КНОПКА "СБРОСИТЬ ВСЁ" ПЕРЕНЕСЕНА НА УРОВЕНЬ ЗАГОЛОВКА ---
        btn_reset_all_text = "Сбросить всё" if self.master.current_lang == "ru" else "Reset All"
        self.btn_reset_all = ctk.CTkButton(
            self.frame_settings, text=btn_reset_all_text, font=("Calibri", 12, "bold"),
            width=100, height=28, fg_color="#552222", hover_color="#772222",
            command=self.reset_all_paths
        )
        # Ставим в ту же строку (row=0), но прижимаем вправо (sticky="e")
        self.btn_reset_all.grid(row=0, column=0, sticky="e", padx=20, pady=(30, 20))
        # --------------------------------------

        # Скроллируемый список путей (поднимаем на row=1)
        self.settings_scroll = ctk.CTkScrollableFrame(self.frame_settings, fg_color="transparent")
        self.settings_scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))

        self.path_entries = {}
        # Строим UI настроек после небольшой задержки, чтобы данные плагинов успели загрузиться
        self.after(200, self.build_settings_ui)
    # --- НАПОЛНЕНИЕ ВКЛАДКИ ЭКСПОРТА / ИМПОРТА ---
        self.sync_wrapper = ctk.CTkFrame(self.frame_sync, fg_color="transparent")
        self.sync_wrapper.pack(expand=True, anchor="center", pady=20)

        sync_title_ru = "Управление данными"
        sync_title_en = "Data Management"
        self.lbl_sync_title = ctk.CTkLabel(
            self.sync_wrapper, 
            text=sync_title_ru if self.master.current_lang == "ru" else sync_title_en, 
            font=self.master.font_title
        )
        self.lbl_sync_title.pack(pady=(0, 25))

        # --- КАРТОЧКА 1: ПУТИ ---
        self.card_paths = ctk.CTkFrame(self.sync_wrapper, fg_color="#1a1a1a", corner_radius=8, width=460)
        self.card_paths.pack(fill="x", pady=(0, 15))
        
        lbl_paths_text = "Индивидуальные пути установки" if self.master.current_lang == "ru" else "Custom Installation Paths"
        lbl_paths = ctk.CTkLabel(self.card_paths, text=lbl_paths_text, font=("Calibri", 14, "bold"), text_color="#cccccc")
        lbl_paths.pack(pady=(15, 10))

        btn_frame_paths = ctk.CTkFrame(self.card_paths, fg_color="transparent")
        btn_frame_paths.pack(fill="x", padx=20, pady=(0, 20))
        
        self.btn_export_paths = ctk.CTkButton(
            btn_frame_paths, text="Экспорт" if self.master.current_lang == "ru" else "Export", 
            font=("Calibri", 14, "bold"), fg_color="#333333", hover_color="#444444", height=35, 
            command=self.export_paths
        )
        self.btn_export_paths.pack(side="left", expand=True, fill="x", padx=(0, 5))

        self.btn_import_paths = ctk.CTkButton(
            btn_frame_paths, text="Импорт" if self.master.current_lang == "ru" else "Import", 
            font=("Calibri", 14, "bold"), fg_color=self.master.accent_color, hover_color=self.master.accent_hover, height=35, 
            command=self.import_paths
        )
        self.btn_import_paths.pack(side="right", expand=True, fill="x", padx=(5, 0))

        # --- КАРТОЧКА 2: ПЛАГИНЫ ---
        self.card_plugins = ctk.CTkFrame(self.sync_wrapper, fg_color="#1a1a1a", corner_radius=8, width=460)
        self.card_plugins.pack(fill="x", pady=(0, 25))

        lbl_custom_text = "Пользовательские плагины" if self.master.current_lang == "ru" else "Custom Plugins"
        lbl_custom = ctk.CTkLabel(self.card_plugins, text=lbl_custom_text, font=("Calibri", 14, "bold"), text_color="#cccccc")
        lbl_custom.pack(pady=(15, 10))

        btn_frame_custom = ctk.CTkFrame(self.card_plugins, fg_color="transparent")
        btn_frame_custom.pack(fill="x", padx=20, pady=(0, 20))

        self.btn_export_custom = ctk.CTkButton(
            btn_frame_custom, text="Экспорт" if self.master.current_lang == "ru" else "Export", 
            font=("Calibri", 14, "bold"), fg_color="#333333", hover_color="#444444", height=35, 
            command=self.export_custom
        )
        self.btn_export_custom.pack(side="left", expand=True, fill="x", padx=(0, 5))

        self.btn_import_custom = ctk.CTkButton(
            btn_frame_custom, text="Импорт" if self.master.current_lang == "ru" else "Import", 
            font=("Calibri", 14, "bold"), fg_color=self.master.accent_color, hover_color=self.master.accent_hover, height=35, 
            command=self.import_custom
        )
        self.btn_import_custom.pack(side="right", expand=True, fill="x", padx=(5, 0))

        # --- ПРИМЕЧАНИЕ ---
        sync_warn_ru = "💡 Примечание: при импорте плагинов локальные файлы (.aex, .zip) не переносятся.\nОни будут скачаны заново с Google Диска (если указана ссылка)."
        sync_warn_en = "💡 Note: when importing plugins, local files (.aex, .zip) are not transferred.\nThey will be re-downloaded from Google Drive (if a link was provided)."
        lbl_sync_warn = ctk.CTkLabel(
            self.sync_wrapper, 
            text=sync_warn_ru if self.master.current_lang == "ru" else sync_warn_en, 
            font=("Calibri", 12), text_color="#888888", justify="center"
        )
        lbl_sync_warn.pack(pady=(0, 0))
        # ---------------------------------------------

        # Центрированная обертка-карточка
        self.form_wrapper = ctk.CTkFrame(self.frame_custom, fg_color="transparent", width=440)
        self.form_wrapper.pack(expand=True, anchor="center", pady=20)

        self.lbl_custom_title = ctk.CTkLabel(self.form_wrapper, text=t["custom_title"], font=self.master.font_title)
        self.lbl_custom_title.pack(pady=(0, 20))

        # Название
        self.entry_c_name = ctk.CTkEntry(self.form_wrapper, placeholder_text=t["c_name_ph"], width=440, height=35)
        self.entry_c_name.pack(pady=(0, 15))

        # Версия и Размер
        row1 = ctk.CTkFrame(self.form_wrapper, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 15))
        
        self.entry_c_ver = ctk.CTkEntry(row1, placeholder_text=t["c_ver_ph"], height=35)
        self.entry_c_ver.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.entry_c_size = ctk.CTkEntry(row1, placeholder_text=t["c_size_ph"], height=35)
        self.entry_c_size.pack(side="right", fill="x", expand=True, padx=(10, 0))

        # Типы файлов (Множественный выбор под вид SegmentedButton)
        self.lbl_type = ctk.CTkLabel(self.form_wrapper, text=t["plugin_type"], font=("Calibri", 13))
        self.lbl_type.pack(anchor="w", pady=(0, 5))
        
        self.type_container = ctk.CTkFrame(self.form_wrapper, fg_color="#1a1a1a", corner_radius=6, width=440, height=34)
        self.type_container.pack(fill="x", pady=(0, 15))
        self.type_container.pack_propagate(False)
        
        self.selected_types = {"zip"}
        self.type_buttons = {}
        types_list = [("ZIP", "zip"), ("EXE", "exe"), ("AEX", "aex"), ("JSX", "jsx"), ("REG", "reg")]
        
        # Размещаем кнопки вплотную друг к другу
        for t_name, t_id in types_list:
            btn = ctk.CTkButton(self.type_container, text=t_name, height=30, width=10, corner_radius=4,
                                font=("Calibri", 12, "bold"),
                                fg_color=self.master.accent_color if t_id in self.selected_types else "transparent",
                                hover_color=self.master.accent_hover if t_id in self.selected_types else "#333333",
                                text_color="#ffffff" if t_id in self.selected_types else "#cccccc",
                                command=lambda tid=t_id: self.toggle_type(tid))
            btn.pack(side="left", fill="both", expand=True, padx=2, pady=2)
            self.type_buttons[t_id] = btn

# Главная кнопка действия (теперь она над динамическими путями)
        self.btn_add_custom = ctk.CTkButton(
            self.form_wrapper, text=t["custom_add_btn"], font=self.master.font_btn,
            fg_color=self.master.accent_color, hover_color=self.master.accent_hover,
            width=440, height=45, corner_radius=8, command=self.save_custom_plugin
        )
        self.btn_add_custom.pack(fill="x", pady=(10, 15))

        # Словари для хранения динамических переменных (Источник и Путь) для каждого типа
        self.type_source_vars = {}
        self.type_gdrive_vars = {}
        self.type_local_vars = {}
        self.type_source_containers = {}
        self.path_vars = {"zip": ctk.StringVar(), "aex": ctk.StringVar(), "jsx": ctk.StringVar()}
        
        self.dynamic_path_wrapper = ctk.CTkFrame(self.form_wrapper, fg_color="transparent")
        self.dynamic_path_wrapper.pack(fill="x")

        # Инициализация
        self.update_path_visibility()
        self.populate_logs()
        self.show_changelog() 

        if hasattr(self.master, 'icon_path') and os.path.exists(self.master.icon_path):
            self.after(200, lambda: self.iconbitmap(self.master.icon_path))
        self.after(10, self._set_dark_titlebar)

    def _set_dark_titlebar(self):
        if sys.platform == "win32":
            try:
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                
                # 1. Сначала пытаемся включить стандартный темный режим (для Win 10 и Win 11)
                # Пробуем ключ 20 (для новых сборок) и 19 (для старых сборок)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
                
                # 2. ЕСЛИ ХОЧЕШЬ ЗАДАТЬ СВОЙ ЦВЕТ (Работает в Windows 11)
                # Раскомментируй две строчки ниже.
                # Формат цвета здесь хитрый: 0x00BBGGRR (Синий, Зеленый, Красный), а не обычный RGB!
                # Например, 0x00242424 - это цвет фона твоего приложения (#242424)
                
                # DWMWA_CAPTION_COLOR = 35
                # ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(ctypes.c_int(0x00242424)), ctypes.sizeof(ctypes.c_int))
                
            except Exception as e:
                print(f"Не удалось применить темный/цветной заголовок: {e}")

    def _reset_sidebar(self):
        self.frame_changelog.grid_forget()
        self.frame_logs.grid_forget()
        self.frame_custom.grid_forget()
        self.frame_settings.grid_forget()
        self.frame_sync.grid_forget() # <--- ДОБАВЛЕНО
        self.btn_tab_changelog.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_logs.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_custom.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_settings.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_sync.configure(fg_color="transparent", text_color="#cccccc") # <--- ДОБАВЛЕНО
        
    def show_sync(self):
        self._reset_sidebar()
        self.frame_sync.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_sync.configure(fg_color=self.master.accent_color, text_color="#ffffff")

    def show_changelog(self):
        self._reset_sidebar()
        self.frame_changelog.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_changelog.configure(fg_color=self.master.accent_color, text_color="#ffffff")

    def show_logs(self):
        self._reset_sidebar()
        self.frame_logs.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_logs.configure(fg_color=self.master.accent_color, text_color="#ffffff")

    def show_custom(self):
        self._reset_sidebar()
        self.master.reload_custom_plugins()
        self.frame_custom.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_custom.configure(fg_color=self.master.accent_color, text_color="#ffffff")

    def show_settings(self):
        self._reset_sidebar()
        self.frame_settings.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_settings.configure(fg_color=self.master.accent_color, text_color="#ffffff")
        
    def toggle_type(self, t_id):
        if t_id in self.selected_types:
            self.selected_types.remove(t_id)
        else:
            self.selected_types.add(t_id)
            
        for tid, btn in self.type_buttons.items():
            is_sel = tid in self.selected_types
            btn.configure(fg_color=self.master.accent_color if is_sel else "transparent")
            btn.configure(hover_color=self.master.accent_hover if is_sel else "#333333")
            btn.configure(text_color="#ffffff" if is_sel else "#cccccc")
            
        self.update_path_visibility()
            
        self.update_path_visibility()
        
    def update_path_visibility(self):
        for widget in self.dynamic_path_wrapper.winfo_children():
            widget.destroy()

        t = self.master.lang_dict[self.master.current_lang]
        
        for t_id in sorted(list(self.selected_types)):
            if t_id not in self.type_source_vars:
                self.type_source_vars[t_id] = ctk.StringVar(value="Google Drive")
                self.type_gdrive_vars[t_id] = ctk.StringVar()
                self.type_local_vars[t_id] = ctk.StringVar()

            card = ctk.CTkFrame(self.dynamic_path_wrapper, fg_color="#1a1a1a", corner_radius=6)
            card.pack(fill="x", pady=(0, 10))

            lbl_title = ctk.CTkLabel(card, text=f"Настройка для .{t_id.upper()}", font=("Calibri", 14, "bold"), text_color=self.master.accent_color)
            lbl_title.pack(anchor="w", padx=10, pady=(5, 5))

            seg = ctk.CTkSegmentedButton(
                card, variable=self.type_source_vars[t_id], values=["Google Drive", t["local_file"]], 
                command=lambda val, tid=t_id: self._toggle_type_source(tid, val),
                height=28, selected_color=self.master.accent_color, selected_hover_color=self.master.accent_hover
            )
            seg.pack(fill="x", padx=10, pady=(0, 10))

            input_container = ctk.CTkFrame(card, fg_color="transparent")
            input_container.pack(fill="x", padx=10, pady=(0, 10))
            self.type_source_containers[t_id] = input_container
            self._build_type_source_inputs(t_id) 

            # Поле для целевого пути (только для файлов, которые нужно куда-то копировать/распаковывать)
            if t_id in ["zip", "aex", "jsx"]:
                path_frame = ctk.CTkFrame(card, fg_color="transparent", height=35)
                path_frame.pack(fill="x", padx=10, pady=(0, 10))

                # --- ДОБАВЛЕН ТЕКСТ СЛЕВА ---
                lbl_text = "Папка:" if self.master.current_lang == "ru" else "Folder:"
                lbl = ctk.CTkLabel(path_frame, text=lbl_text, font=("Calibri", 13, "bold"), text_color="#aaaaaa")
                lbl.pack(side="left", padx=(0, 10))

                entry_path = ctk.CTkEntry(path_frame, textvariable=self.path_vars[t_id], height=35)
                entry_path.pack(side="left", fill="x", expand=True, padx=(0, 10))

                btn_path = ctk.CTkButton(path_frame, text=t["browse"], width=80, height=35, fg_color="#333333", hover_color="#444444", command=lambda tid=t_id: self.browse_specific_path(tid))
                btn_path.pack(side="right")

    def _build_type_source_inputs(self, t_id):
        container = self.type_source_containers[t_id]
        for widget in container.winfo_children(): widget.destroy()
        
        t = self.master.lang_dict[self.master.current_lang]
        mode = self.type_source_vars[t_id].get()
        
        if mode == "Google Drive":
            # --- ДОБАВЛЕН ТЕКСТ СЛЕВА ---
            lbl_text = "Ссылка:" if self.master.current_lang == "ru" else "Link:"
            lbl = ctk.CTkLabel(container, text=lbl_text, font=("Calibri", 13, "bold"), text_color="#aaaaaa")
            lbl.pack(side="left", padx=(0, 10))

            entry = ctk.CTkEntry(container, textvariable=self.type_gdrive_vars[t_id], height=35)
            entry.pack(side="left", fill="x", expand=True)
        else:
            # --- ДОБАВЛЕН ТЕКСТ СЛЕВА ---
            lbl_text = "Файл:" if self.master.current_lang == "ru" else "File:"
            lbl = ctk.CTkLabel(container, text=lbl_text, font=("Calibri", 13, "bold"), text_color="#aaaaaa")
            lbl.pack(side="left", padx=(0, 10))

            entry = ctk.CTkEntry(container, textvariable=self.type_local_vars[t_id], height=35)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
            
            btn = ctk.CTkButton(container, text=t["browse"], width=80, height=35, fg_color="#333333", hover_color="#444444", command=lambda tid=t_id: self.browse_custom_local_type(tid))
            btn.pack(side="right")

    def _toggle_type_source(self, t_id, value):
        self._build_type_source_inputs(t_id)

    def browse_custom_local_type(self, t_id):
        file_path = filedialog.askopenfilename(title=f"Выберите файл .{t_id}")
        if file_path:
            self.type_local_vars[t_id].set(file_path)
    def build_settings_ui(self):
        for widget in self.settings_scroll.winfo_children():
            widget.destroy()

        t = self.master.lang_dict[self.master.current_lang]
        
        # Фильтруем плагины, которым реально нужен путь (исключаем exe-установщики)
        exe_installers = ["BCC", "Mocha_Pro", "Sapphire", "RedGiant"] 
        
        for p_data in self.master.plugins_data:
            p_name = p_data[0]
            if p_name in exe_installers or p_data[2] == "CUSTOM":
                continue # Пропускаем EXE и Custom (у custom свои пути)

            row = ctk.CTkFrame(self.settings_scroll, fg_color="#1a1a1a", corner_radius=6)
            row.pack(fill="x", pady=5)

            lbl = ctk.CTkLabel(row, text=p_name, font=("Calibri", 14, "bold"), width=120, anchor="w")
            lbl.pack(side="left", padx=10, pady=10)

            var = ctk.StringVar(value=self.master.custom_plugin_paths.get(p_name, ""))
            self.path_entries[p_name] = var
            
            # При изменении текста в поле - сохраняем
            var.trace_add("write", lambda *args, name=p_name, v=var: self._save_single_path(name, v))

            entry = ctk.CTkEntry(row, textvariable=var, placeholder_text=t.get("custom_path_ph", ""), height=30)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

            btn_reset = ctk.CTkButton(row, text="✖", width=30, height=30, 
                                      fg_color="#552222", hover_color="#772222", 
                                      command=lambda v=var: v.set(""))
            btn_reset.pack(side="right", padx=(0, 10))

            btn = ctk.CTkButton(row, text=t["browse"], width=70, height=30, fg_color="#333333", hover_color="#444444", 
                                command=lambda n=p_name, v=var: self._browse_plugin_path(n, v))
            btn.pack(side="right", padx=(0, 5))

    def _browse_plugin_path(self, plugin_name, string_var):
        folder = filedialog.askdirectory(title=f"Выберите папку для {plugin_name}")
        if folder:
            string_var.set(folder)
            self._save_single_path(plugin_name, string_var)

    def _save_single_path(self, plugin_name, string_var):
        self.master.custom_plugin_paths[plugin_name] = string_var.get()
        self.master.save_settings()
    
    def _save_single_path(self, plugin_name, string_var):
        self.master.custom_plugin_paths[plugin_name] = string_var.get()
        self.master.save_settings()

    def reset_all_paths(self):
        msg_ru = "Вы уверены, что хотите сбросить все пути установки по умолчанию?"
        msg_en = "Are you sure you want to reset all custom installation paths to default?"
        confirm_msg = msg_ru if self.master.current_lang == "ru" else msg_en
        
        if messagebox.askyesno("Подтверждение / Confirm", confirm_msg):
            self.master.custom_plugin_paths.clear()
            for var in self.path_entries.values():
                var.set("")
            self.master.save_settings()

    def browse_specific_path(self, t_id):
        folder = filedialog.askdirectory(title="Выберите целевую папку")
        if folder:
            self.path_vars[t_id].set(folder)

    def save_custom_plugin(self):
        name = self.entry_c_name.get().strip().replace(" ", "_")
        ver = self.entry_c_ver.get().strip() or "1.0"
        size = self.entry_c_size.get().strip() or "? MB"
        
        if not name:
            messagebox.showwarning("Внимание", "Поле 'Название' обязательно!")
            return

        if not self.selected_types:
            messagebox.showwarning("Внимание", "Необходимо выбрать хотя бы один тип файла!")
            return

        if any(p[0].lower() == name.lower() for p in self.master.plugins_data):
            messagebox.showerror("Ошибка", "Плагин с таким именем уже существует!")
            return

        # --- СБОР ИНФОРМАЦИИ ПО КАЖДОМУ ТИПУ ФАЙЛА ---
        custom_files = {}
        for t_id in self.selected_types:
            mode = "gdrive" if self.type_source_vars[t_id].get() == "Google Drive" else "local"
            file_info = {"source": mode}
            c_filename = f"{name}_{t_id}.{t_id}" # Например: MyPlugin_aex.aex
            file_info["filename"] = c_filename

            if mode == "gdrive":
                raw_link = self.type_gdrive_vars[t_id].get().strip()
                file_info["gdrive_id"] = self.master.extract_gdrive_id(raw_link)
            else:
                local_src = self.type_local_vars[t_id].get().strip()
                if not local_src or not os.path.exists(local_src):
                    messagebox.showerror("Ошибка", f"Локальный файл для .{t_id} не выбран или не существует!")
                    return
                # Копируем файл в наш кэш сразу
                dest_path = os.path.join(self.master.base_dir, c_filename)
                try: shutil.copy2(local_src, dest_path)
                except Exception as e:
                    messagebox.showerror("Ошибка", f"Не удалось скопировать .{t_id} файл в кэш:\n{e}")
                    return
            
            # Сохраняем путь установки (если пользователь его указал)
            if t_id in self.path_vars:
                val = self.path_vars[t_id].get().strip()
                if val: file_info["target_path"] = val
                
            custom_files[t_id] = file_info

        # --- СОХРАНЕНИЕ В JSON ---
        custom_db_path = os.path.join(self.master.base_dir, "custom_plugins.json")
        data = {"plugins": []}
        if os.path.exists(custom_db_path):
            try:
                with open(custom_db_path, "r", encoding="utf-8") as f: data = json.load(f)
            except Exception: pass

        new_plugin = {
            "name": name, "version": ver, "size": size,
            "bat_path": "CUSTOM",
            "c_types": list(self.selected_types),
            "custom_files": custom_files # Новая структура!
        }
        data["plugins"].append(new_plugin)
        
        try:
            with open(custom_db_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить конфиг: {e}")
            return

        # Обновление UI основного окна
        self.master.plugins_data.append((name, ver, "CUSTOM", False, size, None))
        clean_kw = name.lower().split('_')[0].split('-')[0]
        self.master.plugin_keywords[name] = [name.lower(), clean_kw]
        self.master.custom_data[name] = new_plugin

        var = ctk.BooleanVar(value=False)
        display_text = f"★ {name} [v{ver}]  ({size})"
        cb_kwargs = {
            "font": self.master.font_main, "checkbox_width": 18, "checkbox_height": 18,
            "border_width": 1, "corner_radius": 4, "fg_color": "#4CAF50", "hover_color": "#45a049"
        }
        cb = ctk.CTkCheckBox(
            self.master.scrollable_checkbox_frame, text=display_text, variable=var, 
            command=lambda n=name, v=var: self.master.on_plugin_toggle(n, v), **cb_kwargs
        )
        cb.pack(anchor="w", pady=3, padx=5)
        self.master.checkboxes.append((name, var))

        messagebox.showinfo("Успех", f"Плагин {name} добавлен в список!")
        
        # Очистка полей
        self.entry_c_name.delete(0, 'end')
        for tid in self.selected_types:
            self.type_gdrive_vars[tid].set("")
            self.type_local_vars[tid].set("")
            if tid in self.path_vars: self.path_vars[tid].set("")
# === ЛОГИКА ЭКСПОРТА И ИМПОРТА ===
    def export_paths(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")], title="Экспорт путей / Export Paths")
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(self.master.custom_plugin_paths, f, ensure_ascii=False, indent=4)
                messagebox.showinfo("Успех", "Пути успешно экспортированы!")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Ошибка экспорта: {e}")

    def import_paths(self):
        filepath = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")], title="Импорт путей / Import Paths")
        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.master.custom_plugin_paths.update(data)
                self.master.save_settings()
                self.build_settings_ui() # Обновляем UI путей
                messagebox.showinfo("Успех", "Пути успешно импортированы и сохранены!")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Ошибка импорта (неверный формат файла): {e}")

    def export_custom(self):
        custom_db_path = os.path.join(self.master.base_dir, "custom_plugins.json")
        if not os.path.exists(custom_db_path):
            messagebox.showwarning("Внимание", "Нет добавленных плагинов для экспорта.")
            return
        filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")], title="Экспорт плагинов / Export Plugins")
        if filepath:
            try:
                shutil.copy2(custom_db_path, filepath)
                messagebox.showinfo("Успех", "База пользовательских плагинов экспортирована!")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Ошибка экспорта: {e}")

    def import_custom(self):
        filepath = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")], title="Импорт плагинов / Import Plugins")
        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if "plugins" not in data:
                    messagebox.showerror("Ошибка", "Неверный формат файла (отсутствует ключ 'plugins').")
                    return

                custom_db_path = os.path.join(self.master.base_dir, "custom_plugins.json")
                existing_data = {"plugins": []}
                if os.path.exists(custom_db_path):
                    with open(custom_db_path, 'r', encoding='utf-8') as f: existing_data = json.load(f)
                
                # Добавляем только тех, кого еще нет в списке (проверка по имени)
                existing_names = {p["name"] for p in existing_data.get("plugins", [])}
                added_count = 0
                for p in data.get("plugins", []):
                    if p["name"] not in existing_names:
                        existing_data["plugins"].append(p)
                        existing_names.add(p["name"])
                        added_count += 1
                
                with open(custom_db_path, 'w', encoding='utf-8') as f:
                    json.dump(existing_data, f, ensure_ascii=False, indent=4)
                    
                self.master.reload_custom_plugins() # Подгружаем в главный интерфейс
                messagebox.showinfo("Успех", f"Импортировано новых плагинов: {added_count}.")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Ошибка импорта: {e}")

    def populate_logs(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        for entry in self.master.persistent_log_history:
            self.log_textbox.insert("end", entry[self.master.current_lang] + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def append_log(self, text):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", text)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def update_last_log(self, text):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("end-2c linestart", "end-1c")
        self.log_textbox.insert("end-1c", text)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def export_persistent_logs(self):
        if not self.master.persistent_log_history:
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Сохранить логи / Save Logs"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(f"--- AE Plugins Installer Persistent Logs ({self.master.CURRENT_VERSION}) ---\n\n")
                    for entry in self.master.persistent_log_history:
                        f.write(entry[self.master.current_lang] + "\n")
                self.master.log(f"✅ Логи успешно сохранены в:\n{file_path}", f"✅ Logs successfully saved to:\n{file_path}")
            except Exception as e:
                self.master.log(f"❌ Ошибка при сохранении файла: {e}", f"❌ Error saving file: {e}")


# =================================================================
# ОСНОВНОЕ ОКНО
# =================================================================
class AksiomInstaller(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.CURRENT_VERSION = "5.0" 
        self.DB_URL = "https://raw.githubusercontent.com/Aks-iom/aksiom-installer-data/refs/heads/main/plugins.json"
        
        self.CHANGELOG_TEXT = {
            "ru": (
                "Версия Beta 5.0: \n"
                "- Добавление 26-ой версии ае в качестве эксперемента\n"
                "- Окно дополнительных настроек\n"
                "- Возможность добавления своих плагинов\n"
                "- Возможность изменения пути установки стандартных плагинов\n"
                "- Список изменений\n"
                "- Импорт и экспорт данных\n"
                "- Добавление версий и размера в списке плагинов\n"
                "- Улушение работы с Google drive\n"
                "-Добавление папки кэша\n"
                "- Исправление багов и минорные обновления\n"
            ),
            "en": (
                "Version Beta 5.0: \n"
                "- Adding AE version 26 as an experiment\n"
                "- Additional settings window\n"
                "- Ability to add custom plugins\n"
                "- Ability to change the installation path for default plugins\n"
                "- Changelog\n"
                "-Data import and export\n"
                "-Adding versions and sizes to the plugin list\n"
                "-Improvements to Google Drive\n"
                "-Adding a cache folder\n"
                "-Bug fixes and minor updates\n"
            )
        }

        self.title("Ae plugins installer Beta 5.0")
        self.geometry("820x600")
        self.resizable(False, False)
        self.configure(fg_color="#242424")
        
        self.font_main = ("Calibri", 14)
        self.font_title = ("Calibri", 16, "bold")
        self.font_btn = ("Calibri", 18, "bold")

        self.accent_color = "#6658cc"
        self.accent_hover = "#5346a6"

        self.log_history = []              
        self.persistent_log_history = []   
        
        self.current_lang = "ru"
        self.advanced_window = None 
        self.custom_install_path_var = ctk.StringVar()
        
        self.lang_dict = {
            "ru": {
                "title": "Ae plugins installer Beta 5.0",
                "version_lbl": "Выбор версии After Effects",
                "plugins_lbl": "Выбор плагинов",
                "select_all": "Выбрать все",
                "wait": "Ожидание...",
                "install_btn": "Установить выбранные",
                "log_lbl": "Журнал событий",
                "clear_log_btn": "Очистить логи",
                "export_log_btn": "Сохранить логи",
                "source_btn": "Источник",
                "complete": "Операция завершена",
                "advanced_btn": "Дополнительно",
                "tab_changelog": "Список изменений",
                "tab_logs": "Логи",
                "tab_custom": "Свои плагины",
                "tab_settings": "Индивидуальные пути",
                "settings_title": "Индивидуальные пути",
                "settings_path_desc": "Пользовательский путь установки (работает только для простых плагинов)",
                "custom_title": "Конфигуратор пользовательских плагинов",
                "c_name_ph": "Название (например: MyPlugin)",
                "c_ver_ph": "Версия",
                "c_size_ph": "Размер",
                "plugin_type": "Выбор типа файлов",
                "source_type": "Источник:",
                "local_file": "Локальный файл",
                "select_file": "Файл...",
                "custom_add_btn": "Создать и добавить в список",
                "custom_path_ph": "Оставьте пустым для стандарта...",
                "path_zip": "Путь распаковки .zip (опционально):",
                "path_aex": "Путь копирования .aex (опционально):",
                "path_jsx": "Путь копирования .jsx/.jsxbin (опционально):",
                "browse": "Обзор"
            },
            "en": {
                "title": "Ae plugins Installer Beta 5.0",
                "version_lbl": "Select After Effects Version",
                "plugins_lbl": "Select Plugins",
                "select_all": "Select All",
                "wait": "Waiting...",
                "install_btn": "Install Selected",
                "log_lbl": "Event Log",
                "clear_log_btn": "Clear Logs",
                "export_log_btn": "Export Logs",
                "source_btn": "Source",
                "complete": "Operation Complete",
                "advanced_btn": "Advanced",
                "tab_changelog": "Changelog",
                "tab_logs": "Logs",
                "tab_custom": "Custom Plugins",
                "tab_settings": "Individual Paths",
                "settings_title": "Individual Paths",
                "settings_path_desc": "Custom installation path (works only for simple plugins)",
                "custom_title": "Custom Plugin Configurator",
                "c_name_ph": "Name (e.g., MyPlugin)",
                "c_ver_ph": "Version (e.g., 1.0)",
                "c_size_ph": "Size (e.g., 15 MB)",
                "plugin_type": "File types (select required):",
                "source_type": "Source:",
                "local_file": "Local File",
                "select_file": "File...",
                "custom_add_btn": "Create and Add to List",
                "custom_path_ph": "Leave empty for default...",
                "path_zip": "Extraction path for .zip (optional):",
                "path_aex": "Copy path for .aex (optional):",
                "path_jsx": "Copy path for .jsx/.jsxbin (optional):",
                "browse": "Browse"
            }
        }

        self.grid_columnconfigure(0, weight=0) 
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        if getattr(sys, 'frozen', False):
            app_dir = os.path.dirname(sys.executable)
            bundle_dir = sys._MEIPASS
        else:
            app_dir = os.path.dirname(os.path.abspath(__file__))
            bundle_dir = app_dir

        self.cache_dir = os.path.join(app_dir, "Aksiom-installer-cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.base_dir = self.cache_dir

        self.icon_path = os.path.join(bundle_dir, "logo.ico")
        if os.path.exists(self.icon_path):
            self.iconbitmap(self.icon_path)

        self.plugins_data = []
        self.plugin_keywords = {}
        self.gdrive_file_ids = {}
        self.custom_data = {}

        self.load_plugins_database()
        self.create_widgets()
        
        self.version_var.trace_add("write", lambda *args: self.check_installed_plugins())
        self.check_installed_plugins()
        self.check_for_updates()
        # --- ДОБАВИТЬ В КОНЕЦ __init__ класса AksiomInstaller ---
        self.settings_file = os.path.join(self.base_dir, "settings.json")
        self.custom_plugin_paths = self.load_settings()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except: pass
        return {}

    def save_settings(self):
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.custom_plugin_paths, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Ошибка сохранения настроек: {e}")

    def on_closing(self):
        # Проверяем, идет ли установка (если главная кнопка заблокирована - значит идет)
        if self.btn_install.cget("state") == "disabled":
            msg_ru = "Установка плагинов еще не завершена.\nВы уверены, что хотите прервать процесс и выйти?"
            msg_en = "Installation is not finished.\nAre you sure you want to abort the process and exit?"
            msg = msg_ru if self.current_lang == "ru" else msg_en
            
            # Запрашиваем подтверждение
            if not messagebox.askyesno("Внимание / Warning", msg):
                return # Если пользователь нажал "Нет", отменяем закрытие
        
        # Если установки нет или пользователь согласился выйти:
        self.destroy() # Закрываем окна
        os._exit(0)    # ЖЕСТКО убиваем процесс Python, чтобы он не висел в диспетчере задач

    def extract_gdrive_id(self, url):
        if not url: return ""
        match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
        if match: return match.group(1)
        match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
        if match: return match.group(1)
        if "http" not in url and "/" not in url:
            return url
        return ""
    def get_dynamic_paths(self, ae_version):
        custom_path = self.custom_install_path_var.get().strip()
        
        if not custom_path:
            base = rf"C:\Program Files\Adobe\Adobe After Effects {ae_version}"
            return os.path.join(base, "Support Files", "Plug-ins"), os.path.join(base, "Support Files", "Scripts", "ScriptUI Panels")

        if os.path.basename(custom_path.rstrip("\\/")).lower() == "adobe":
            base = os.path.join(custom_path, f"Adobe After Effects {ae_version}")
            return os.path.join(base, "Support Files", "Plug-ins"), os.path.join(base, "Support Files", "Scripts", "ScriptUI Panels")

        if "after effects" in custom_path.lower():
            return os.path.join(custom_path, "Support Files", "Plug-ins"), os.path.join(custom_path, "Support Files", "Scripts", "ScriptUI Panels")

        return custom_path, custom_path
    
    def resolve_target_path(self, plugin_name, default_path, full_ae_version):
        """Возвращает кастомный путь, если он задан, и автоматически меняет год версии AE"""
        custom_path = self.custom_plugin_paths.get(plugin_name, "").strip()
        
        if custom_path:
            # Если путь содержит "After Effects 20XX", заменяем год на выбранную версию
            if full_ae_version != "None":
                # Ищем "After Effects " (или "Adobe After Effects ") и 4 цифры года
                custom_path = re.sub(
                    r'(?i)(After Effects\s*)20\d{2}', 
                    rf'\g<1>{full_ae_version}', 
                    custom_path
                )
            return custom_path
            
        return default_path

    def load_plugins_database(self):
        local_db_path = os.path.join(self.base_dir, "plugins.json")
        custom_db_path = os.path.join(self.base_dir, "custom_plugins.json")

        try:
            req = urllib.request.Request(self.DB_URL, headers={'User-Agent': 'AksiomInstaller'})
            with urllib.request.urlopen(req, timeout=3) as response:
                data = json.loads(response.read().decode('utf-8'))
            with open(local_db_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception:
            if os.path.exists(local_db_path):
                with open(local_db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else: data = None

        if data and "plugins" in data:
            for p in data["plugins"]:
                name = p["name"]
                self.plugins_data.append((
                    name, p.get("version", "1.0"), p.get("bat_path", ""), 
                    p.get("needs_version", False), p.get("size", ""), p.get("md5", None)
                ))
                self.plugin_keywords[name] = p.get("keywords", [name.lower()])
                self.gdrive_file_ids[name] = p.get("gdrive_id", "")
        else:
            messagebox.showerror("Ошибка", "Не удалось загрузить базу плагинов. Проверьте интернет-соединение.")
            sys.exit()

        if os.path.exists(custom_db_path):
            try:
                with open(custom_db_path, 'r', encoding='utf-8') as f:
                    c_data = json.load(f)
                for p in c_data.get("plugins", []):
                    name = p["name"]
                    self.plugins_data.append((
                        name, p.get("version", "1.0"), "CUSTOM", 
                        False, p.get("size", ""), None
                    ))
                    
                    clean_kw = name.lower().split('_')[0].split('-')[0]
                    self.plugin_keywords[name] = [name.lower(), clean_kw]
                    
                    self.gdrive_file_ids[name] = p.get("gdrive_id", "")
                    self.custom_data[name] = p
            except Exception as e:
                print(f"Ошибка загрузки кастомных плагинов: {e}")
                
    def reload_custom_plugins(self):
        """Подгружает новые плагины из JSON 'на лету', если они были изменены вручную"""
        custom_db_path = os.path.join(self.base_dir, "custom_plugins.json")
        if not os.path.exists(custom_db_path): return
        
        try:
            with open(custom_db_path, 'r', encoding='utf-8') as f:
                c_data = json.load(f)
            
            for p in c_data.get("plugins", []):
                name = p["name"]
                # Добавляем только если такого плагина еще нет в приложении
                if name not in self.custom_data:
                    self.plugins_data.append((
                        name, p.get("version", "1.0"), "CUSTOM", 
                        False, p.get("size", ""), None
                    ))
                    
                    clean_kw = name.lower().split('_')[0].split('-')[0]
                    self.plugin_keywords[name] = [name.lower(), clean_kw]
                    
                    self.gdrive_file_ids[name] = p.get("gdrive_id", "")
                    self.custom_data[name] = p

                    # Автоматически создаем чекбокс в основном окне
                    var = ctk.BooleanVar(value=False)
                    display_text = f"★ {name} [v{p.get('version', '1.0')}]  ({p.get('size', '')})"
                    
                    cb_kwargs = {
                        "font": self.font_main, "checkbox_width": 18, "checkbox_height": 18,
                        "border_width": 1, "corner_radius": 4, "fg_color": "#4CAF50", "hover_color": "#45a049"
                    }
                    
                    cb = ctk.CTkCheckBox(
                        self.scrollable_checkbox_frame, text=display_text, variable=var, 
                        command=lambda n=name, v=var: self.on_plugin_toggle(n, v), **cb_kwargs
                    )
                    cb.pack(anchor="w", pady=3, padx=5)
                    self.checkboxes.append((name, var))
            
            # Обновляем подсветку установленных
            self.check_installed_plugins()
        except Exception as e:
            print(f"Ошибка перезагрузки кастомных плагинов: {e}")

    def create_widgets(self):
        left_width = 340
        t = self.lang_dict[self.current_lang]

        self.left_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.left_frame.grid(row=0, column=0, padx=(20, 10), pady=20, sticky="nsew")

        self.lbl_version = ctk.CTkLabel(self.left_frame, text=t["version_lbl"], font=self.font_title)
        self.lbl_version.pack(anchor="w", pady=(0, 5))

        self.version_var = ctk.StringVar(value="None")
        versions = ["None", "20", "21", "22", "23", "24", "25" , "26"]
        
        self.segmented_button = ctk.CTkSegmentedButton(
            self.left_frame, values=versions, variable=self.version_var,
            font=("Calibri", 12), selected_color=self.accent_color,
            selected_hover_color=self.accent_hover, unselected_color="#1a1a1a",
            unselected_hover_color="#2a2a2a", text_color="#cccccc"
        )
        self.segmented_button.pack(anchor="w", fill="x", pady=(0, 15))

        self.lbl_plugins = ctk.CTkLabel(self.left_frame, text=t["plugins_lbl"], font=self.font_title)
        self.lbl_plugins.pack(anchor="w", pady=(0, 5))

        self.scrollable_checkbox_frame = ctk.CTkScrollableFrame(
            self.left_frame, width=left_width, height=270, fg_color="#1a1a1a", corner_radius=8
        )
        self.scrollable_checkbox_frame.pack(anchor="w", fill="x", pady=(0, 15))

        self.checkboxes = []
        self.select_all_var = ctk.BooleanVar(value=False)
        
        cb_kwargs = {
            "font": self.font_main, "checkbox_width": 18, "checkbox_height": 18,
            "border_width": 1, "corner_radius": 4, "fg_color": self.accent_color,
            "hover_color": self.accent_hover
        }

        self.cb_select_all = ctk.CTkCheckBox(
            self.scrollable_checkbox_frame, text=t["select_all"], variable=self.select_all_var, 
            command=self.toggle_all, **cb_kwargs
        )
        self.cb_select_all.pack(anchor="w", pady=(5, 5), padx=5)

        for plugin_name, version, bat_path, _, size, _ in self.plugins_data:
            var = ctk.BooleanVar(value=False)
            
            prefix = "★ " if bat_path == "CUSTOM" else ""
            custom_color = "#4CAF50" if bat_path == "CUSTOM" else self.accent_color
            custom_hover = "#45a049" if bat_path == "CUSTOM" else self.accent_hover
            
            ver_text = "" if version == "1.0" else f" [v{version}]"
            display_text = f"{prefix}{plugin_name}{ver_text}  ({size})"
            
            specific_kwargs = cb_kwargs.copy()
            specific_kwargs["fg_color"] = custom_color
            specific_kwargs["hover_color"] = custom_hover

            cb = ctk.CTkCheckBox(
                self.scrollable_checkbox_frame, text=display_text, variable=var, 
                command=lambda n=plugin_name, v=var: self.on_plugin_toggle(n, v), **specific_kwargs
            )
            cb.pack(anchor="w", pady=3, padx=5)
            self.checkboxes.append((plugin_name, var))

        self.progress_label = ctk.CTkLabel(self.left_frame, text=t["wait"], font=self.font_main, text_color="#aaaaaa")
        self.progress_label.pack(anchor="w", pady=(5, 0))

        self.progressbar = ctk.CTkProgressBar(
            self.left_frame, width=left_width, height=16, 
            progress_color=self.accent_color, fg_color="#333333", corner_radius=6
        )
        self.progressbar.pack(anchor="w", fill="x", pady=(5, 10)) 
        self.progressbar.set(0)

        self.btn_install = ctk.CTkButton(
            self.left_frame, text=t["install_btn"], font=self.font_btn, 
            fg_color=self.accent_color, hover_color=self.accent_hover, 
            height=40, width=left_width, corner_radius=8, command=self.start_installation
        )
        self.btn_install.pack(anchor="w", fill="x", pady=(0, 5))

        self.footer_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        self.footer_frame.pack(side="bottom", fill="x", pady=(10, 0)) 

        self.btn_github = ctk.CTkButton(
            self.footer_frame, text="GitHub", font=("Calibri", 13, "underline"), width=0, height=20,
            fg_color="transparent", text_color="#888888", hover_color="#333333",
            command=lambda: webbrowser.open("https://github.com/Aks-iom/Aks-iom-AE-Plugins-install-script")
        )
        self.btn_github.pack(side="left", padx=(0, 10))

        self.btn_telegram = ctk.CTkButton(
            self.footer_frame, text="Telegram", font=("Calibri", 13, "underline"), width=0, height=20,
            fg_color="transparent", text_color="#888888", hover_color="#333333",
            command=lambda: webbrowser.open("https://t.me/AE_plugins_script")
        )
        self.btn_telegram.pack(side="left", padx=(0, 10))
        
        self.btn_source = ctk.CTkButton(
            self.footer_frame, text=t["source_btn"], font=("Calibri", 13, "underline"), width=0, height=20,
            fg_color="transparent", text_color="#888888", hover_color="#333333",
            command=lambda: webbrowser.open("https://satvrn.li/windows")
        )
        self.btn_source.pack(side="left")

        # === ПРАВАЯ ПАНЕЛЬ ===
        self.right_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.right_frame.grid(row=0, column=1, padx=(10, 20), pady=20, sticky="nsew")

        self.right_top_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.right_top_frame.pack(fill="x", pady=(0, 5))

        self.lbl_log = ctk.CTkLabel(self.right_top_frame, text=t["log_lbl"], font=self.font_title)
        self.lbl_log.pack(side="left")

        self.btn_lang = ctk.CTkButton(
            self.right_top_frame, text="EN", font=("Calibri", 13, "bold"), width=35, height=24,
            fg_color="#333333", hover_color="#444444", corner_radius=4, command=self.toggle_language
        )
        self.btn_lang.pack(side="right")

        self.log_container = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.log_container.pack(fill="both", expand=True)

        self.log_textbox = ctk.CTkTextbox(
            self.log_container, font=("Consolas", 12), fg_color="#151515", text_color="#cccccc",
            border_width=1, border_color="#333333", corner_radius=8
        )
        self.log_textbox.pack(fill="both", expand=True)
        self.log_textbox.configure(state="disabled")

        self.right_bottom_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.right_bottom_frame.pack(fill="x", pady=(10, 0))

        self.btn_advanced = ctk.CTkButton(
            self.right_bottom_frame, text=t["advanced_btn"], font=self.font_main, 
            fg_color="#333333", hover_color="#444444", height=30, width=0, 
            corner_radius=6, command=self.open_advanced_window
        )
        self.btn_advanced.pack(side="right")

        self.btn_clear_log = ctk.CTkButton(
            self.right_bottom_frame, text=t["clear_log_btn"], font=self.font_main, fg_color="#333333", 
            hover_color="#444444", height=30, width=0, corner_radius=6, command=self.clear_logs
        )
        self.btn_clear_log.pack(side="right", padx=(0, 10))

        self.target_y = None
        self._is_animating = False
        self.scrollable_checkbox_frame._mouse_wheel_all = self.smooth_wheel_event

    def open_advanced_window(self):
        if self.advanced_window is None or not self.advanced_window.winfo_exists():
            self.advanced_window = AdvancedWindow(self)
        else:
            self.advanced_window.deiconify()  
            self.advanced_window.focus()      

    def toggle_language(self):
        self.current_lang = "en" if self.current_lang == "ru" else "ru"
        t = self.lang_dict[self.current_lang]
        
        self.title(t["title"])
        self.lbl_version.configure(text=t["version_lbl"])
        self.lbl_plugins.configure(text=t["plugins_lbl"])
        self.cb_select_all.configure(text=t["select_all"])
        
        if self.progressbar.get() == 0 or self.progressbar.get() == 1.0:
            status_text = t["complete"] if self.progressbar.get() == 1.0 else t["wait"]
            self.progress_label.configure(text=status_text)
            
        self.btn_install.configure(text=t["install_btn"])
        self.lbl_log.configure(text=t["log_lbl"])
        self.btn_clear_log.configure(text=t["clear_log_btn"])
        self.btn_advanced.configure(text=t["advanced_btn"])
        self.btn_source.configure(text=t["source_btn"])
        self.btn_lang.configure(text="RU" if self.current_lang == "en" else "EN")

        if hasattr(self, 'btn_update'):
            self.btn_update.configure(text=self.update_btn_texts[self.current_lang])

        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        for entry in self.log_history:
            self.log_textbox.insert("end", entry[self.current_lang] + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

        if self.advanced_window and self.advanced_window.winfo_exists():
            aw = self.advanced_window
            aw.title(t["advanced_btn"])
            aw.btn_tab_changelog.configure(text=t["tab_changelog"])
            aw.btn_tab_logs.configure(text=t["tab_logs"])
            aw.btn_tab_custom.configure(text=t["tab_custom"])
            aw.btn_tab_settings.configure(text=t["tab_settings"])
            aw.btn_export.configure(text=t["export_log_btn"])
            
            aw.lbl_settings_title.configure(text=t["settings_title"])
            aw.lbl_settings_desc.configure(text=t["settings_path_desc"])
            aw.entry_global_path.configure(placeholder_text=t["custom_path_ph"])
            aw.btn_browse_global.configure(text=t["browse"])

            aw.lbl_custom_title.configure(text=t["custom_title"])
            aw.lbl_type.configure(text=t["plugin_type"])
            aw.lbl_source.configure(text=t["source_type"])
            
            aw.entry_c_name.configure(placeholder_text=t["c_name_ph"])
            aw.entry_c_ver.configure(placeholder_text=t["c_ver_ph"])
            aw.entry_c_size.configure(placeholder_text=t["c_size_ph"])
            
            aw.seg_source.configure(values=["Google Drive", t["local_file"]])
            aw.entry_c_local.configure(placeholder_text=t["select_file"])
            aw.btn_c_local_browse.configure(text=t["browse"])
            aw.btn_add_custom.configure(text=t["custom_add_btn"])
            
            aw.update_path_visibility()

            aw.changelog_text.configure(state="normal")
            aw.changelog_text.delete("1.0", "end")
            aw.changelog_text.insert("1.0", self.CHANGELOG_TEXT[self.current_lang])
            aw.changelog_text.configure(state="disabled")
            aw.populate_logs()
        
    def log(self, ru_text, en_text=None):
        if en_text is None:
            en_text = ru_text
        self.after(0, self._safe_log, ru_text, en_text)

    def _gdown_log(self, text):
        self._safe_log(text, text)

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

        if self.advanced_window and self.advanced_window.winfo_exists():
            self.advanced_window.append_log(msg + "\n")

    def _update_last_log_line(self, message):
        entry = {"ru": message, "en": message}
        if self.log_history:
            self.log_history[-1] = entry
        if self.persistent_log_history:
            self.persistent_log_history[-1] = entry
            
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("end-2c linestart", "end-1c")
        self.log_textbox.insert("end-1c", message)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

        if self.advanced_window and self.advanced_window.winfo_exists():
            self.advanced_window.update_last_log(message)

    def clear_logs(self):
        self.log_history.clear()
        self.log_textbox.configure(state="normal") 
        self.log_textbox.delete("1.0", "end")        
        self.log_textbox.configure(state="disabled") 

    def extract_version_number(self, text):
        text = text.replace(',', '.')
        match = re.search(r'\d+(\.\d+)*', text)
        return match.group() if match else "0.0"

    def extract_display_version(self, text):
        match = re.search(r'(?:Beta\s*)?\d+(?:[.,]\d+)*', text, re.IGNORECASE)
        if match:
            found = match.group()
            return "V.Beta " + found[4:].strip() if found.lower().startswith('beta') else "V." + found
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
                self.log("[ОБНОВЛЕНИЕ] Подключение к серверам GitHub...", "[UPDATE] Connecting to GitHub servers...")
                url = "https://api.github.com/repos/Aks-iom/Aks-iom-AE-Plugins-install-script/releases/tags/AE"
                req = urllib.request.Request(url, headers={'User-Agent': 'AksiomInstaller'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode())
                    release_name = data.get("name", "")
                    if self.is_version_newer(release_name, self.CURRENT_VERSION):
                        display_version = self.extract_display_version(release_name)
                        self.after(0, lambda: self.show_update_button(display_version))
                        self.log(f"[ОБНОВЛЕНИЕ] Найдена новая версия: {display_version}", f"[UPDATE] New version found: {display_version}")
                    else:
                        self.log("[ОБНОВЛЕНИЕ] У вас установлена актуальная версия.", "[UPDATE] You have the latest version installed.")
            except Exception: pass 
        threading.Thread(target=fetch, daemon=True).start()

    def show_update_button(self, release_title):
        self.update_btn_texts = {
            "ru": f"Скачать обновление ({release_title})",
            "en": f"Download update ({release_title})"
        }
        self.btn_update = ctk.CTkButton(
            self.right_bottom_frame,
            text=self.update_btn_texts[self.current_lang],
            font=self.font_main, fg_color=self.accent_color, hover_color=self.accent_hover,
            height=30, corner_radius=6,
            command=lambda: webbrowser.open("https://github.com/Aks-iom/Aks-iom-AE-Plugins-install-script/releases/tag/AE")
        )
        self.btn_update.pack(side="left", fill="x", expand=True, padx=(0, 10))

    def smooth_wheel_event(self, event):
        if not self.scrollable_checkbox_frame._check_if_mouse_inside(event.x_root, event.y_root):
            return
        canvas = self.scrollable_checkbox_frame._parent_canvas
        top, bottom = canvas.yview()
        if top == 0.0 and bottom == 1.0: return
        direction = -1 if event.delta > 0 else 1
        step = 0.06 
        if self.target_y is None: self.target_y = top
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

    def get_search_dirs(self, ae_version):
        dirs = [
            r"C:\Program Files\BorisFX", r"C:\Program Files\BorisFX\ContinuumAE\14\lib",
            r"C:\Program Files\Adobe", r"C:\Program Files\Maxon", r"C:\Program Files\GenArts",
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
            r"C:\ProgramData", r"C:\ProgramData\VideoCopilot", r"C:\ProgramData\GenArts\rlm"
        ]
        script_panels = glob.glob(r"C:\Program Files\Adobe\Adobe After Effects*\Support Files\Scripts\ScriptUI Panels")
        dirs.extend(script_panels)
        
        plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)
        if os.path.exists(plugins_dir): dirs.append(plugins_dir)
        if os.path.exists(scripts_dir): dirs.append(scripts_dir)
            
        return dirs
    
    def is_plugin_installed(self, plugin_name, ae_version):
        search_dirs = []
        has_custom_path = False
        
        # 1. Проверяем, задан ли индивидуальный путь в настройках (для основных плагинов)
        custom_main_path = self.custom_plugin_paths.get(plugin_name, "").strip()
        if custom_main_path:
            # Автоматически меняем год на выбранную версию AE
            resolved_path = self.resolve_target_path(plugin_name, "", ae_version)
            search_dirs.append(resolved_path)
            has_custom_path = True
            
        # 2. Проверяем пути для полностью пользовательских плагинов (из вкладки Custom)
        if plugin_name in self.custom_data:
            c_paths = self.custom_data[plugin_name].get("custom_target_paths", {})
            for p in c_paths.values():
                if p:
                    search_dirs.append(p)
                    has_custom_path = True
                    
        # 3. Если индивидуальных путей НЕТ вообще, тогда берем стандартные папки
        if not has_custom_path:
            search_dirs = self.get_search_dirs(ae_version)

        # Отсеиваем папки, которых физически не существует
        valid_dirs = list(set(d for d in search_dirs if os.path.exists(d)))
        keywords = self.plugin_keywords.get(plugin_name, [plugin_name.lower()])
        
        for d in valid_dirs:
            try:
                # Ищем внутри папки и на 2 уровня вглубь
                for root, dirs, files in os.walk(d):
                    level = root.replace(d, '').count(os.sep)
                    if level > 2:
                        del dirs[:] # Дальше 2 уровня не лезем, чтобы не тормозить
                        continue
                        
                    for item in files + dirs:
                        item_lower = item.lower()
                        for kw in keywords:
                            if kw.lower() in item_lower:
                                if plugin_name == "Deep_Glow" and "2" in item_lower and "deep" in item_lower: continue
                                return True
            except Exception: pass
            
        # Проверка лицензии Sapphire нужна только если путь стандартный
        if not has_custom_path and plugin_name == "Sapphire" and glob.glob(r"C:\ProgramData\GenArts\rlm\*.lic"): 
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
                if isinstance(child, ctk.CTkCheckBox) and child.cget("text").replace("★ ", "").startswith(name):
                    child.configure(text_color="#4CAF50" if is_installed else "#cccccc") 

    def toggle_all(self):
        state = self.select_all_var.get()
        for _, var in self.checkboxes: var.set(state)
        if state:
            self.log("\n⚠️ Внимание (RedGiant):\n( Установщик плагинов maxon очень не стабилен поэтому могут возникнуть проблемы )", 
                     "\n⚠️ Warning (RedGiant):\n( Maxon installer is very unstable, so problems may occur )")

    def on_plugin_toggle(self, plugin_name, var):
        self.check_individual_state()
        if plugin_name == "RedGiant" and var.get():
            self.log("\n⚠️ Внимание (RedGiant):\n( Установщик плагинов maxon очень не стабилен поэтому могут возникнуть проблемы )", 
                     "\n⚠️ Warning (RedGiant):\n( Maxon installer is very unstable, so problems may occur )")

    def check_individual_state(self):
        all_checked = all(var.get() for _, var in self.checkboxes)
        self.select_all_var.set(all_checked)

    def _update_progress_ui(self, text, value):
        self.progress_label.configure(text=text)
        self.progressbar.set(value)

    def _finish_process_ui(self):
        t = self.lang_dict[self.current_lang]
        self.progress_label.configure(text=t["complete"])
        self.progressbar.set(1.0)
        try: self.check_installed_plugins() 
        except Exception as e: self._safe_log(f"[ОШИБКА UI] {e}")
        self.btn_install.configure(state="normal")

    def calculate_md5(self, file_path):
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def verify_archive_integrity(self, zip_path, expected_md5=None):
        self.log("🔎 Проверка целостности архива...", "🔎 Verifying archive integrity...")
        if expected_md5:
            actual_md5 = self.calculate_md5(zip_path)
            if actual_md5 != expected_md5:
                self.log(f"❌ [ОШИБКА] MD5 не совпадает! Ожидался: {expected_md5}, Получен: {actual_md5}", f"❌ [ERROR] MD5 mismatch! Expected: {expected_md5}, Got: {actual_md5}")
                return False
            else: self.log("✅ MD5 хэш совпадает.", "✅ MD5 hash matched.")
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                bad_file = z.testzip()
                if bad_file:
                    self.log(f"❌ [ОШИБКА] Найден битый файл внутри архива: {bad_file}", f"❌ [ERROR] Corrupted file found inside archive: {bad_file}")
                    return False
            self.log("✅ Структура архива не повреждена.", "✅ Archive structure is intact.")
            return True
        except zipfile.BadZipFile:
            self.log("❌ [ОШИБКА] Файл не является ZIP-архивом или критически поврежден.", "❌ [ERROR] File is not a ZIP archive or is critically corrupted.")
            return False
        except Exception as e:
            self.log(f"❌ [ОШИБКА] Ошибка при проверке архива: {e}", f"❌ [ERROR] Archive check error: {e}")
            return False

    def download_from_gdrive(self, file_id, destination_path):
        if not file_id:
            self.log(f"[ОШИБКА] Не указан Google Drive ID.", f"[ERROR] Google Drive ID is not specified.")
            return False
        original_stderr = sys.stderr
        try:
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            self.log(f"[*] Загрузка файла с Google Диска...", f"[*] Downloading file from Google Drive...")
            sys.stderr = GdownLogCatcher(self, original_stderr)
            output = gdown.download(id=file_id, output=destination_path, quiet=False)
            sys.stderr = original_stderr
            if output:
                self.log(f"[+] Файл скачан.", f"[+] File downloaded.")
                return True
            else:
                self.log(f"[ОШИБКА] Не удалось скачать файл.", f"[ERROR] Failed to download file.")
                return False
        except Exception as e:
            sys.stderr = original_stderr
            self.log(f"[ОШИБКА] Критическая ошибка скачивания: {e}", f"[ERROR] Critical download error: {e}")
            return False

    def start_installation(self):
        self.clear_logs()
        ae_version = self.version_var.get()
        if ae_version != "None": full_ae_version = "20" + ae_version
        else:
            self.log("[ОШИБКА] Пожалуйста, выберите версию After Effects!", "[ERROR] Please select an After Effects version!")
            return

        selected_plugins, skipped_plugins = [], []

        for name, var in self.checkboxes:
            if var.get(): 
                is_installed = self.is_plugin_installed(name, full_ae_version)
                if is_installed:
                    skipped_plugins.append(name)
                    var.set(False) 
                else: selected_plugins.append(name)

        if skipped_plugins:
            self.log(f"[ОТМЕНА] Следующие плагины уже установлены и были пропущены:", f"[CANCELLED] The following plugins are already installed and were skipped:")
            self.log(f"   -> {', '.join(skipped_plugins)}")

        if not selected_plugins:
            self.log("\n[ИНФО] Нет плагинов для установки.", "\n[INFO] No plugins to install.")
            return

        self.btn_install.configure(state="disabled")
        self.log(f"\n{'='*50}")
        self.log(f"🚀 НАЧАЛО УСТАНОВКИ ДЛЯ AFTER EFFECTS {full_ae_version}", f"🚀 STARTING INSTALLATION FOR AFTER EFFECTS {full_ae_version}")
        self.log(f"{'='*50}")
        threading.Thread(target=self.run_install_process, args=(full_ae_version, selected_plugins), daemon=True).start()

    def execute_native_install(self, plugin_name, ae_version, src_dir): # Убрали custom_install_path
        plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)

        if plugin_name == "BCC":
            setup_exe = os.path.join(src_dir, "BCC_Setup.exe")
            subprocess.run([setup_exe, "/s", "/v/qb", "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True, creationflags=CREATE_NO_WINDOW)
            bcc_lib = r"C:\Program Files\BorisFX\ContinuumAE\14\lib"
            os.makedirs(bcc_lib, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Crack", "Continuum_Common_AE.dll"), bcc_lib)
            prog_data_rlm = r"C:\ProgramData\GenArts\rlm"
            if os.path.exists(prog_data_rlm):
                for lic in glob.glob(os.path.join(prog_data_rlm, "*.lic")):
                    try: os.remove(lic)
                    except OSError: pass
            shutil.copytree(os.path.join(src_dir, "Crack", "GenArts"), r"C:\ProgramData\GenArts", dirs_exist_ok=True)
            
        elif plugin_name == "Bokeh":
            dest = self.resolve_target_path(plugin_name, os.path.join(plugins_dir, "Plugins Everything"), ae_version)
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Bokeh.aex"), dest)
            
        elif plugin_name == "Deep_Glow":
            dest = self.resolve_target_path(plugin_name, r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore", ae_version)
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Deep Glow.aex"), dest)
            
        elif plugin_name == "Deep_Glow2":
            dest = self.resolve_target_path(plugin_name, r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore", ae_version)
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "DeepGlow2.aex"), dest)
            shutil.copy2(os.path.join(src_dir, "IrisBlurSDK.dll"), dest)
            
        elif plugin_name == "Element":
            # Для Element 3D кастомный путь применяем только к самому плагину .aex
            dest_plugin = self.resolve_target_path(plugin_name, os.path.join(plugins_dir, "VideoCopilot"), ae_version)
            dest_lic = r"C:\ProgramData\VideoCopilot"
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
            dest = self.resolve_target_path(plugin_name, scripts_dir, ae_version)
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Fast_Layers.jsx"), dest)
            
        elif plugin_name == "Flow":
            dest = self.resolve_target_path(plugin_name, r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions\flow", ae_version)
            src_flow = os.path.join(src_dir, "flow-v1.5.2")
            if os.path.exists(src_flow): shutil.copytree(src_flow, dest, dirs_exist_ok=True)
            for csxs in ["CSXS.10", "CSXS.11", "CSXS.12"]:
                try:
                    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Adobe\{csxs}")
                    winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
                    winreg.CloseKey(key)
                except Exception: pass
                
        elif plugin_name == "Fxconsole":
            dest = self.resolve_target_path(plugin_name, os.path.join(plugins_dir, "VideoCopilot"), ae_version)
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "FXConsole.aex"), dest)
            
        elif plugin_name == "Glitchify":
            dest = self.resolve_target_path(plugin_name, os.path.join(plugins_dir, "VideoCopilot"), ae_version)
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Glitchify.aex"), dest)
            
        elif plugin_name == "Mocha_Pro":
            installer_path = os.path.join(src_dir, "mochapro_2026.0.1_adobe_installer.exe")
            subprocess.run([installer_path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True, creationflags=CREATE_NO_WINDOW)
            time.sleep(4)
            subprocess.run(["taskkill", "/F", "/IM", "mochapro.exe", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
            subprocess.run(["taskkill", "/F", "/IM", "mocha.exe", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
            
        elif plugin_name == "RSMB":
            dest = self.resolve_target_path(plugin_name, r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\RSMB", ae_version)
            os.makedirs(dest, exist_ok=True)
            for aex in glob.glob(os.path.join(src_dir, "*.aex")): shutil.copy2(aex, dest)
            
        elif plugin_name == "Saber":
            dest = self.resolve_target_path(plugin_name, os.path.join(plugins_dir, "VideoCopilot"), ae_version)
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(os.path.join(src_dir, "Saber.aex"), dest)
            
        elif plugin_name == "Sapphire":
            installer_path = os.path.join(src_dir, "sapphire_ae_install.exe")
            try: subprocess.run([installer_path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True, creationflags=CREATE_NO_WINDOW)
            except subprocess.CalledProcessError as e:
                if e.returncode == 3010: self.log("   [ИНФО] Установка завершена (требуется перезагрузка ПК)", "   [INFO] Installation complete (PC restart required)")
                else: raise e
                
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
            dest = self.resolve_target_path(plugin_name, r"C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\Twixtor8AE", ae_version)
            os.makedirs(dest, exist_ok=True)
            src_twixtor = os.path.join(src_dir, "Twixtor8AE")
            if os.path.exists(src_twixtor): shutil.copytree(src_twixtor, dest, dirs_exist_ok=True)
            
        elif plugin_name == "Uwu2x":
            cep_base = self.resolve_target_path(plugin_name, r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions", ae_version)
            os.makedirs(cep_base, exist_ok=True)
            src_pro = os.path.join(src_dir, "uwu2x-pro")
            src_norm = os.path.join(src_dir, "uwu2x")
            if os.path.exists(src_pro): shutil.copytree(src_pro, os.path.join(cep_base, "uwu2x-pro"), dirs_exist_ok=True)
            elif os.path.exists(src_norm): shutil.copytree(src_norm, os.path.join(cep_base, "uwu2x"), dirs_exist_ok=True)
            for i in range(10, 17):
                try:
                    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Adobe\CSXS.{i}")
                    winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
                    winreg.CloseKey(key)
                except Exception: pass
                
        elif plugin_name == "Prime_tool":
            cep_path = self.resolve_target_path(plugin_name, r"C:\Program Files (x86)\Common Files\Adobe\CEP\extensions\com.PrimeTools", ae_version)
            os.makedirs(cep_path, exist_ok=True)
            zxp_file = os.path.join(src_dir, "com.PrimeTools.cep.zxp")
            if os.path.exists(zxp_file):
                with zipfile.ZipFile(zxp_file, 'r') as zip_ref: zip_ref.extractall(cep_path)
                
        elif plugin_name == "RedGiant":
            subprocess.run([os.path.join(src_dir, "1_Maxon.exe"), "--mode", "unattended", "--unattendedmodeui", "minimal"], check=True, creationflags=CREATE_NO_WINDOW)
            subprocess.run([os.path.join(src_dir, "2_RedGiant.exe"), "--mode", "unattended", "--unattendedmodeui", "minimal"], check=True, creationflags=CREATE_NO_WINDOW)
            subprocess.run([os.path.join(src_dir, "3_Unlocker.exe"), "/SILENT"], check=True, creationflags=CREATE_NO_WINDOW)
            time.sleep(6)
            subprocess.run(["taskkill", "/F", "/IM", "Maxon App.exe", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
            subprocess.run(["taskkill", "/F", "/IM", "Maxon.exe", "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)

    def run_install_process(self, ae_version, selected_plugins):
        try:
            total = len(selected_plugins)
            native_plugins = [p[0] for p in self.plugins_data]
            custom_install_path = self.custom_install_path_var.get().strip()
            
            for index, plugin_name in enumerate(selected_plugins):
                plugin_info = next((p for p in self.plugins_data if p[0] == plugin_name), None)
                if not plugin_info: continue

                _, _, bat_path, needs_version, _, expected_md5 = plugin_info
                is_custom = plugin_name in self.custom_data
                
                start_pct = index / total
                status_ru = f"Установка: {plugin_name}..."
                status_en = f"Installation: {plugin_name}..."
                self.after(0, self._update_progress_ui, status_ru if self.current_lang == "ru" else status_en, start_pct)
                
                self.log(f"\n" + "-"*40)
                self.log(f"📦 ПЛАГИН: {plugin_name} {'[ПОЛЬЗОВАТЕЛЬСКИЙ]' if is_custom else ''}")
                self.log("-" * 40)

                # ==========================================
                # ОБРАБОТКА ПОЛЬЗОВАТЕЛЬСКИХ ПЛАГИНОВ
                # ==========================================
                if is_custom:
                    c_info = self.custom_data[plugin_name]
                    c_files = c_info.get("custom_files", {})
                    plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)
                    
                    if not c_files:
                        self.log("⚠️ Обнаружен старый формат плагина. Пожалуйста, пересоздайте его через вкладку 'Дополнительно'.")
                        continue

                    # Проходим по каждому типу файла, который нужно установить
                    for t_id, f_info in c_files.items():
                        c_source = f_info.get("source")
                        c_filename = f_info.get("filename")
                        target_file_path = os.path.join(self.base_dir, c_filename)
                        c_target_path = f_info.get("target_path", "")

                        self.log(f"[*] Обработка .{t_id.upper()} файла...")

                        # 1. Скачивание (если нужно)
                        if c_source == "gdrive":
                            file_id = f_info.get("gdrive_id")
                            if file_id and not os.path.exists(target_file_path):
                                self.log(f"    Загрузка файла с Google Диска...")
                                if not self.download_from_gdrive(file_id, target_file_path): continue
                        
                        if not os.path.exists(target_file_path):
                            self.log(f"❌ Файл {c_filename} не найден!")
                            continue

                        # 2. Выполнение действий по типу
                        try:
                            if t_id == "zip":
                                self.log(f"    Распаковка архива...")
                                extract_target = c_target_path if c_target_path else (custom_install_path if custom_install_path else os.path.join(plugins_dir, plugin_name))
                                os.makedirs(extract_target, exist_ok=True)
                                with zipfile.ZipFile(target_file_path, 'r') as zip_ref: 
                                    zip_ref.extractall(extract_target)
                                    
                            elif t_id == "exe":
                                self.log(f"    Запуск установщика...")
                                subprocess.run([target_file_path], check=True)
                                    
                            elif t_id == "aex":
                                self.log(f"    Копирование плагина...")
                                target_dir = c_target_path if c_target_path else plugins_dir
                                os.makedirs(target_dir, exist_ok=True)
                                shutil.copy2(target_file_path, target_dir)
                                    
                            elif t_id == "jsx":
                                self.log(f"    Копирование скрипта...")
                                target_dir = c_target_path if c_target_path else scripts_dir
                                os.makedirs(target_dir, exist_ok=True)
                                shutil.copy2(target_file_path, target_dir)
                                    
                            elif t_id == "reg":
                                self.log(f"    Внесение изменений в реестр...")
                                ctypes.windll.shell32.ShellExecuteW(None, "runas", "reg.exe", f'import "{target_file_path}"', None, 0)
                                time.sleep(1) 

                        except Exception as e:
                            self.log(f"❌ Ошибка при обработке {t_id}: {e}")
                    
                    self.log(f"✅ Установка {plugin_name} завершена.")
                    
                # ==========================================
                # ОБРАБОТКА СТАНДАРТНЫХ ПЛАГИНОВ
                # ==========================================
                else:
                    full_bat_path = os.path.join(self.base_dir, bat_path)
                    plugin_src_dir = os.path.dirname(full_bat_path)
                    zip_path = os.path.join(self.base_dir, f"{plugin_name}.zip")
                    
                    if not os.path.exists(plugin_src_dir):
                        file_id = self.gdrive_file_ids.get(plugin_name)
                        if not self.download_from_gdrive(file_id, zip_path): continue
                        if not self.verify_archive_integrity(zip_path, expected_md5):
                            if os.path.exists(zip_path):
                                try: os.remove(zip_path)
                                except OSError: pass
                            continue

                        self.log(f"[*] Извлечение файлов...", f"[*] Extracting files...")
                        try:
                            with zipfile.ZipFile(zip_path, 'r') as zip_ref: zip_ref.extractall(self.base_dir)
                            self.log(f"[+] Распаковка завершена.", f"[+] Extraction completed.")
                        except Exception as e:
                            self.log(f"[ОШИБКА] Ошибка извлечения: {e}")
                            continue
                        finally:
                            if os.path.exists(zip_path):
                                try: os.remove(zip_path)
                                except OSError: pass

                    try:
                        if plugin_name in native_plugins:
                            self.execute_native_install(plugin_name, ae_version, plugin_src_dir)
                            self.log(f"✅ {plugin_name} успешно установлен.")
                        else: self.log(f"❌ Плагин не поддерживается.")
                    except Exception as e: self.log(f"❌ [ОШИБКА] Сбой: {str(e)}")

                end_pct = (index + 1) / total
                self.after(0, self._update_progress_ui, f"Завершено: {plugin_name}" if self.current_lang == "ru" else f"Completed: {plugin_name}", end_pct)

            self.log(f"\n{'='*50}")
            self.log("🔍 ФИНАЛЬНАЯ ПРОВЕРКА УСТАНОВКИ...", "🔍 FINAL INSTALLATION CHECK...")
            
            for plugin_name in selected_plugins:
                if not self.is_plugin_installed(plugin_name, ae_version):
                    self.log(f"❌ [ОШИБКА] Плагин {plugin_name} не найден после установки!", f"❌ [ERROR] Plugin {plugin_name} not found after installation!")
                else: self.log(f"✅ {plugin_name} корректно установлен.")
            self.log(f"{'='*50}")

        except Exception as e: self.log(f"\n[КРИТИЧЕСКАЯ ОШИБКА] Сбой: {e}")
        finally: self.after(0, self._finish_process_ui)

def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin()
    except: return False

if __name__ == "__main__":
    if is_admin():
        app = AksiomInstaller()
        app.mainloop()
    else:
        if getattr(sys, 'frozen', False):
            params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
        else:
            params = f'"{os.path.abspath(__file__)}" ' + " ".join([f'"{arg}"' for arg in sys.argv[1:]])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        sys.exit()