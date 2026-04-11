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
from functools import lru_cache

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

class AdvancedWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        
        t = self.master.lang_dict.get(self.master.current_lang, self.master.lang_dict["en"])
        self.title(t.get("advanced_btn", "Advanced"))
        self.geometry("780x660")
        self.minsize(750, 600)
        
        self.transient(self.master)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        
        self.sidebar_frame = ctk.CTkFrame(self, width=180, corner_radius=0, fg_color="#1a1a1a")
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)

        self.btn_tab_changelog = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_changelog", "Changelog"), font=self.master.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_changelog
        )
        self.btn_tab_changelog.pack(pady=(20, 5), padx=10, fill="x")

        self.btn_tab_logs = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_logs", "Logs"), font=self.master.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_logs
        )
        self.btn_tab_logs.pack(pady=5, padx=10, fill="x")

        self.btn_tab_custom = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_custom", "Custom Plugins"), font=self.master.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_custom
        )
        self.btn_tab_custom.pack(pady=5, padx=10, fill="x")

        self.btn_tab_settings = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_settings", "Individual Paths"), font=self.master.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_settings
        )
        self.btn_tab_settings.pack(pady=5, padx=10, fill="x")
        
        self.btn_tab_sync = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_sync", "Export / Import"), font=self.master.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_sync
        )
        self.btn_tab_sync.pack(pady=5, padx=10, fill="x")

        self.btn_tab_uninstall = ctk.CTkButton(
            self.sidebar_frame, text=t.get("tab_uninstall", "Uninstall Plugins"), font=self.master.font_main,
            fg_color="transparent", text_color="#cccccc", hover_color="#333333", anchor="w",
            command=self.show_uninstall
        )
        self.btn_tab_uninstall.pack(pady=5, padx=10, fill="x")

        self.frame_changelog = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_logs = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_custom = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.frame_settings = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_sync = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_uninstall = ctk.CTkFrame(self, fg_color="transparent")

        self.changelog_text = ctk.CTkTextbox(
            self.frame_changelog, font=("Calibri", 14), fg_color="#151515", 
            text_color="#bbbbbb", wrap="word", corner_radius=8
        )
        self.changelog_text.pack(fill="both", expand=True, padx=20, pady=20)
        self.changelog_text.insert("1.0", self.master.CHANGELOG_TEXT[self.master.current_lang])
        self.changelog_text.configure(state="disabled")

        self.log_textbox = ctk.CTkTextbox(
            self.frame_logs, font=("Consolas", 12), fg_color="#151515", 
            text_color="#cccccc", wrap="word", corner_radius=8
        )
        self.log_textbox.pack(fill="both", expand=True, padx=20, pady=(20, 10))
        
        self.btn_export = ctk.CTkButton(
            self.frame_logs, text=t.get("export_log_btn", "Export Logs"), font=self.master.font_main, 
            fg_color="#333333", hover_color="#444444", height=35, corner_radius=6, 
            command=self.export_persistent_logs
        )
        self.btn_export.pack(side="right", padx=20, pady=(0, 20))

        self.frame_settings.grid_columnconfigure(0, weight=1)
        self.frame_settings.grid_rowconfigure(1, weight=1) 
        
        self.lbl_settings_title = ctk.CTkLabel(self.frame_settings, text=t.get("settings_title", "Individual Paths"), font=self.master.font_title)
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

        self.lbl_sync_title = ctk.CTkLabel(self.sync_wrapper, text=t.get("sync_title", "Data Management"), font=self.master.font_title)
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
            fg_color=self.master.accent_color, hover_color=self.master.accent_hover, height=35, command=self.import_paths
        )
        self.btn_import_paths.pack(side="right", expand=True, fill="x", padx=(5, 0))

        self.card_plugins = ctk.CTkFrame(self.sync_wrapper, fg_color="#1a1a1a", corner_radius=8, width=460)
        self.card_plugins.pack(fill="x", pady=(0, 25))

        self.lbl_sync_custom = ctk.CTkLabel(self.card_plugins, text=t.get("sync_custom", "Custom Plugins"), font=("Calibri", 14, "bold"), text_color="#cccccc")
        self.lbl_sync_custom.pack(pady=(15, 10))

        btn_frame_custom = ctk.CTkFrame(self.card_plugins, fg_color="transparent")
        btn_frame_custom.pack(fill="x", padx=20, pady=(0, 20))

        self.btn_export_custom = ctk.CTkButton(
            btn_frame_custom, text=t.get("export_btn", "Export"), font=("Calibri", 14, "bold"), 
            fg_color="#333333", hover_color="#444444", height=35, command=self.export_custom
        )
        self.btn_export_custom.pack(side="left", expand=True, fill="x", padx=(0, 5))

        self.btn_import_custom = ctk.CTkButton(
            btn_frame_custom, text=t.get("import_btn", "Import"), font=("Calibri", 14, "bold"), 
            fg_color=self.master.accent_color, hover_color=self.master.accent_hover, height=35, command=self.import_custom
        )
        self.btn_import_custom.pack(side="right", expand=True, fill="x", padx=(5, 0))

        self.lbl_sync_warn = ctk.CTkLabel(self.sync_wrapper, text=t.get("sync_warn", "Note: Local files are not transferred."), font=("Calibri", 12), text_color="#888888", justify="center")
        self.lbl_sync_warn.pack(pady=(0, 0))

        self.form_wrapper = ctk.CTkFrame(self.frame_custom, fg_color="transparent", width=440)
        self.form_wrapper.pack(expand=True, anchor="center", pady=20)

        self.lbl_custom_title = ctk.CTkLabel(self.form_wrapper, text=t.get("custom_title", "Configurator"), font=self.master.font_title)
        self.lbl_custom_title.pack(pady=(0, 20))

        self.entry_c_name = ctk.CTkEntry(self.form_wrapper, placeholder_text=t.get("c_name_ph", "Name"), width=440, height=35)
        self.entry_c_name.pack(pady=(0, 15))

        row1 = ctk.CTkFrame(self.form_wrapper, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 15))
        self.entry_c_ver = ctk.CTkEntry(row1, placeholder_text=t.get("c_ver_ph", "Ver"), height=35)
        self.entry_c_ver.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.entry_c_size = ctk.CTkEntry(row1, placeholder_text=t.get("c_size_ph", "Size"), height=35)
        self.entry_c_size.pack(side="right", fill="x", expand=True, padx=(10, 0))

        self.lbl_type = ctk.CTkLabel(self.form_wrapper, text=t.get("plugin_type", "File Types"), font=("Calibri", 13))
        self.lbl_type.pack(anchor="w", pady=(0, 5))
        
        self.type_container = ctk.CTkFrame(self.form_wrapper, fg_color="#1a1a1a", corner_radius=6, width=440, height=34)
        self.type_container.pack(fill="x", pady=(0, 15))
        self.type_container.pack_propagate(False)
        
        self.selected_types = {"zip"}
        self.type_buttons = {}
        types_list = [("ZIP", "zip"), ("EXE", "exe"), ("AEX", "aex"), ("JSX", "jsx"), ("REG", "reg")]
        
        for t_name, t_id in types_list:
            btn = ctk.CTkButton(self.type_container, text=t_name, height=30, width=10, corner_radius=4,
                                font=("Calibri", 12, "bold"),
                                fg_color=self.master.accent_color if t_id in self.selected_types else "transparent",
                                hover_color=self.master.accent_hover if t_id in self.selected_types else "#333333",
                                text_color="#ffffff" if t_id in self.selected_types else "#cccccc",
                                command=lambda tid=t_id: self.toggle_type(tid))
            btn.pack(side="left", fill="both", expand=True, padx=2, pady=2)
            self.type_buttons[t_id] = btn

        self.btn_add_custom = ctk.CTkButton(
            self.form_wrapper, text=t.get("custom_add_btn", "Add"), font=self.master.font_btn,
            fg_color=self.master.accent_color, hover_color=self.master.accent_hover,
            width=440, height=45, corner_radius=8, command=self.save_custom_plugin
        )
        self.btn_add_custom.pack(fill="x", pady=(10, 15))

        self.type_source_vars = {}
        self.type_gdrive_vars = {}
        self.type_local_vars = {}
        self.type_source_containers = {}
        self.path_vars = {"zip": ctk.StringVar(), "aex": ctk.StringVar(), "jsx": ctk.StringVar()}
        
        self.dynamic_path_wrapper = ctk.CTkFrame(self.form_wrapper, fg_color="transparent")
        self.dynamic_path_wrapper.pack(fill="x")

        self.frame_uninstall.grid_columnconfigure(0, weight=1)
        self.frame_uninstall.grid_rowconfigure(3, weight=1)

        self.lbl_un_title = ctk.CTkLabel(self.frame_uninstall, text=t.get("un_title", "Uninstall Plugins"), font=self.master.font_title)
        self.lbl_un_title.grid(row=0, column=0, pady=(30, 5))
        
        self.lbl_un_desc = ctk.CTkLabel(self.frame_uninstall, text=t.get("un_desc", "Showing plugins installed for selected AE version."), font=("Calibri", 12), text_color="#aaaaaa")
        self.lbl_un_desc.grid(row=1, column=0, pady=(0, 15))

        self.un_version_var = ctk.StringVar(value=self.master.version_var.get())
        versions = ["None", "20", "21", "22", "23", "24", "25" , "26"]
        self.un_version_seg = ctk.CTkSegmentedButton(
            self.frame_uninstall, values=versions, variable=self.un_version_var,
            font=("Calibri", 12), selected_color=self.master.accent_color,
            selected_hover_color=self.master.accent_hover, unselected_color="#1a1a1a", text_color="#cccccc"
        )
        self.un_version_seg.grid(row=2, column=0, pady=(0, 15), padx=20, sticky="ew")
        self.un_version_var.trace_add("write", lambda *args: self.build_uninstall_ui())

        self.uninstall_scroll = ctk.CTkScrollableFrame(self.frame_uninstall, fg_color="transparent")
        self.uninstall_scroll.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 20))

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
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
            except Exception: pass

    def _reset_sidebar(self):
        self.frame_changelog.grid_forget()
        self.frame_logs.grid_forget()
        self.frame_custom.grid_forget()
        self.frame_settings.grid_forget()
        self.frame_sync.grid_forget()
        self.frame_uninstall.grid_forget()
        
        self.btn_tab_changelog.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_logs.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_custom.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_settings.configure(fg_color="transparent", text_color="#cccccc")
        self.btn_tab_sync.configure(fg_color="transparent", text_color="#cccccc") 
        self.btn_tab_uninstall.configure(fg_color="transparent", text_color="#cccccc")

    def show_uninstall(self):
        self._reset_sidebar()
        self.frame_uninstall.grid(row=0, column=1, sticky="nsew")
        self.btn_tab_uninstall.configure(fg_color=self.master.accent_color, text_color="#ffffff")
        
        current_main_ver = self.master.version_var.get()
        if self.un_version_var.get() != current_main_ver:
            self.un_version_var.set(current_main_ver) 
        else:
            self.build_uninstall_ui()

    def build_uninstall_ui(self):
        for widget in self.uninstall_scroll.winfo_children(): widget.destroy()

        t = self.master.lang_dict.get(self.master.current_lang, self.master.lang_dict["en"])
        ae_ver = self.un_version_var.get()
        if ae_ver == "None":
            lbl = ctk.CTkLabel(self.uninstall_scroll, text=t.get("un_select_ae", "Please select an AE version from the list above."), text_color="#cc5555")
            lbl.pack(pady=20)
            return

        full_ver = "20" + ae_ver
        installed_any = False

        sorted_checkboxes = sorted(self.master.checkboxes, key=lambda x: x[0].lower())

        for name, var in sorted_checkboxes:
            if self.master.is_plugin_installed(name, full_ver):
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
        t = self.master.lang_dict.get(self.master.current_lang, self.master.lang_dict["en"])
        confirm = messagebox.askyesno(t.get("un_confirm_title", "Confirm"), f"{t.get('un_confirm_msg', 'Uninstall')} {plugin_name}?")
        if confirm:
            self.master.uninstall_plugin(plugin_name, full_ver)
            self.master.check_installed_plugins()
            self.master.after(200, self.build_uninstall_ui)

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
        self.build_settings_ui()
        
    def toggle_type(self, t_id):
        if t_id in self.selected_types: self.selected_types.remove(t_id)
        else: self.selected_types.add(t_id)
            
        for tid, btn in self.type_buttons.items():
            is_sel = tid in self.selected_types
            btn.configure(fg_color=self.master.accent_color if is_sel else "transparent")
            btn.configure(hover_color=self.master.accent_hover if is_sel else "#333333")
            btn.configure(text_color="#ffffff" if is_sel else "#cccccc")
        self.update_path_visibility()
        
    def update_path_visibility(self):
        for widget in self.dynamic_path_wrapper.winfo_children(): widget.destroy()
        t = self.master.lang_dict.get(self.master.current_lang, self.master.lang_dict["en"])
        
        for t_id in sorted(list(self.selected_types)):
            if t_id not in self.type_source_vars:
                self.type_source_vars[t_id] = ctk.StringVar(value="Google Drive")
                self.type_gdrive_vars[t_id] = ctk.StringVar()
                self.type_local_vars[t_id] = ctk.StringVar()

            card = ctk.CTkFrame(self.dynamic_path_wrapper, fg_color="#1a1a1a", corner_radius=6)
            card.pack(fill="x", pady=(0, 10))

            lbl_title = ctk.CTkLabel(card, text=f"{t.get('setup_for', 'Setup for')} .{t_id.upper()}", font=("Calibri", 14, "bold"), text_color=self.master.accent_color)
            lbl_title.pack(anchor="w", padx=10, pady=(5, 5))

            seg = ctk.CTkSegmentedButton(
                card, variable=self.type_source_vars[t_id], values=["Google Drive", t.get("local_file", "Local")], 
                command=lambda val, tid=t_id: self._toggle_type_source(tid, val),
                height=28, selected_color=self.master.accent_color, selected_hover_color=self.master.accent_hover
            )
            seg.pack(fill="x", padx=10, pady=(0, 10))

            input_container = ctk.CTkFrame(card, fg_color="transparent")
            input_container.pack(fill="x", padx=10, pady=(0, 10))
            self.type_source_containers[t_id] = input_container
            self._build_type_source_inputs(t_id) 

            if t_id in ["zip", "aex", "jsx"]:
                path_frame = ctk.CTkFrame(card, fg_color="transparent", height=35)
                path_frame.pack(fill="x", padx=10, pady=(0, 10))
                lbl_text = t.get("folder_lbl", "Folder:")
                lbl = ctk.CTkLabel(path_frame, text=lbl_text, font=("Calibri", 13, "bold"), text_color="#aaaaaa")
                lbl.pack(side="left", padx=(0, 10))
                entry_path = ctk.CTkEntry(path_frame, textvariable=self.path_vars[t_id], height=35)
                entry_path.pack(side="left", fill="x", expand=True, padx=(0, 10))
                btn_path = ctk.CTkButton(path_frame, text=t.get("browse", "Browse"), width=80, height=35, fg_color="#333333", hover_color="#444444", command=lambda tid=t_id: self.browse_specific_path(tid))
                btn_path.pack(side="right")

    def _build_type_source_inputs(self, t_id):
        container = self.type_source_containers[t_id]
        for widget in container.winfo_children(): widget.destroy()
        t = self.master.lang_dict.get(self.master.current_lang, self.master.lang_dict["en"])
        mode = self.type_source_vars[t_id].get()
        
        if mode == "Google Drive":
            lbl = ctk.CTkLabel(container, text=t.get("link_lbl", "Link:"), font=("Calibri", 13, "bold"), text_color="#aaaaaa")
            lbl.pack(side="left", padx=(0, 10))
            entry = ctk.CTkEntry(container, textvariable=self.type_gdrive_vars[t_id], height=35)
            entry.pack(side="left", fill="x", expand=True)
        else:
            lbl = ctk.CTkLabel(container, text=t.get("file_lbl", "File:"), font=("Calibri", 13, "bold"), text_color="#aaaaaa")
            lbl.pack(side="left", padx=(0, 10))
            entry = ctk.CTkEntry(container, textvariable=self.type_local_vars[t_id], height=35)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
            btn = ctk.CTkButton(container, text=t.get("browse", "Browse"), width=80, height=35, fg_color="#333333", hover_color="#444444", command=lambda tid=t_id: self.browse_custom_local_type(tid))
            btn.pack(side="right")

    def _toggle_type_source(self, t_id, value): self._build_type_source_inputs(t_id)

    def browse_custom_local_type(self, t_id):
        t = self.master.lang_dict.get(self.master.current_lang, self.master.lang_dict["en"])
        file_path = filedialog.askopenfilename(title=f"{t.get('select_file', 'Select file')} .{t_id}")
        if file_path: self.type_local_vars[t_id].set(file_path)

    def build_settings_ui(self):
        for widget in self.settings_scroll.winfo_children(): widget.destroy()
        t = self.master.lang_dict.get(self.master.current_lang, self.master.lang_dict["en"])
        exe_installers = ["BCC", "Mocha_Pro", "Sapphire", "RedGiant", "RSMB"]
        
        for p_data in self.master.plugins_data:
            p_name = p_data[0]
            if p_name in exe_installers or p_data[2] == "CUSTOM": continue 

            row = ctk.CTkFrame(self.settings_scroll, fg_color="#1a1a1a", corner_radius=6)
            row.pack(fill="x", pady=5)

            lbl = ctk.CTkLabel(row, text=p_name, font=("Calibri", 14, "bold"), width=120, anchor="w")
            lbl.pack(side="left", padx=10, pady=10)

            var = ctk.StringVar(value=self.master.custom_plugin_paths.get(p_name, ""))
            self.path_entries[p_name] = var
            var.trace_add("write", lambda *args, name=p_name, v=var: self._save_single_path(name, v))

            entry = ctk.CTkEntry(row, textvariable=var, placeholder_text=t.get("custom_path_ph", ""), height=30)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

            btn_reset = ctk.CTkButton(row, text="✖", width=30, height=30, fg_color="#552222", hover_color="#772222", command=lambda v=var: v.set(""))
            btn_reset.pack(side="right", padx=(0, 10))

            btn = ctk.CTkButton(row, text=t.get("browse", "Browse"), width=70, height=30, fg_color="#333333", hover_color="#444444", command=lambda n=p_name, v=var: self._browse_plugin_path(n, v))
            btn.pack(side="right", padx=(0, 5))

    def _browse_plugin_path(self, plugin_name, string_var):
        t = self.master.lang_dict.get(self.master.current_lang, self.master.lang_dict["en"])
        folder = filedialog.askdirectory(title=f"{t.get('select_folder', 'Select folder for')} {plugin_name}")
        if folder:
            string_var.set(folder)
            self._save_single_path(plugin_name, string_var)

    def _save_single_path(self, plugin_name, string_var):
        self.master.custom_plugin_paths[plugin_name] = string_var.get()
        self.master.save_settings()

    def reset_all_paths(self):
        t = self.master.lang_dict.get(self.master.current_lang, self.master.lang_dict["en"])
        if messagebox.askyesno(t.get("reset_confirm_title", "Confirm"), t.get("reset_confirm_msg", "Reset all paths?")):
            self.master.custom_plugin_paths.clear()
            for var in self.path_entries.values(): var.set("")
            self.master.save_settings()

    def browse_specific_path(self, t_id):
        t = self.master.lang_dict.get(self.master.current_lang, self.master.lang_dict["en"])
        folder = filedialog.askdirectory(title=t.get('target_folder', 'Target folder'))
        if folder: self.path_vars[t_id].set(folder)

    def save_custom_plugin(self):
        t = self.master.lang_dict.get(self.master.current_lang, self.master.lang_dict["en"])
        name = self.entry_c_name.get().strip().replace(" ", "_")
        ver = self.entry_c_ver.get().strip() or "1.0"
        size = self.entry_c_size.get().strip() or "? MB"
        
        if not name or not self.selected_types:
            messagebox.showwarning(t.get("warn_title", "Warning"), t.get("warn_fields", "Fields required!"))
            return

        if any(p[0].lower() == name.lower() for p in self.master.plugins_data):
            messagebox.showerror(t.get("err_title", "Error"), t.get("err_exists", "Plugin exists!"))
            return

        custom_files = {}
        for t_id in self.selected_types:
            mode = "gdrive" if self.type_source_vars[t_id].get() == "Google Drive" else "local"
            file_info = {"source": mode}
            c_filename = f"{name}_{t_id}.{t_id}"
            file_info["filename"] = c_filename

            if mode == "gdrive":
                raw_link = self.type_gdrive_vars[t_id].get().strip()
                file_info["gdrive_id"] = self.master.extract_gdrive_id(raw_link)
            else:
                local_src = self.type_local_vars[t_id].get().strip()
                if not local_src or not os.path.exists(local_src):
                    messagebox.showerror(t.get("err_title", "Ошибка"), f"Неверный или отсутствующий локальный файл для .{t_id}")
                    return
                dest_path = os.path.join(self.master.base_dir, c_filename)
                try: 
                    shutil.copy2(local_src, dest_path)
                except (OSError, PermissionError) as e: 
                    messagebox.showerror(t.get("err_title", "Ошибка"), str(e))
                    return
            
            if t_id in self.path_vars:
                val = self.path_vars[t_id].get().strip()
                if val: file_info["target_path"] = val
                
            custom_files[t_id] = file_info

        custom_db_path = os.path.join(self.master.base_dir, "custom_plugins.json")
        data = {"plugins": []}
        if os.path.exists(custom_db_path):
            try:
                with open(custom_db_path, "r", encoding="utf-8") as f: data = json.load(f)
            except json.JSONDecodeError as e: 
                print(f"JSON Decode Error (custom_plugins.json): {e}")

        new_plugin = {"name": name, "version": ver, "size": size, "bat_path": "CUSTOM", "c_types": list(self.selected_types), "custom_files": custom_files}
        data["plugins"].append(new_plugin)
        
        try:
            with open(custom_db_path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
        except OSError as e: 
            print(f"Error writing to custom_plugins.json: {e}")
            return

        self.master.plugins_data.append((name, ver, "CUSTOM", False, size, None))
        self.master.plugin_keywords[name] = [name.lower(), name.lower().split('_')[0].split('-')[0]]
        self.master.custom_data[name] = new_plugin

        var = ctk.BooleanVar(value=False)
        cb = ctk.CTkCheckBox(
            self.master.scrollable_checkbox_frame, text=f"★ {name} [v{ver}]  ({size})", variable=var, 
            command=lambda n=name, v=var: self.master.on_plugin_toggle(n, v),
            font=self.master.font_main, checkbox_width=18, checkbox_height=18,
            border_width=1, corner_radius=4, fg_color="#4CAF50", hover_color="#45a049"
        )
        cb.pack(anchor="w", pady=3, padx=5)
        self.master.checkboxes.append((name, var))
        self.master.checkbox_widgets[name] = cb 
        
        self.entry_c_name.delete(0, 'end')
        for tid in self.selected_types:
            self.type_gdrive_vars[tid].set("")
            self.type_local_vars[tid].set("")
            if tid in self.path_vars: self.path_vars[tid].set("")

    def export_paths(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f: json.dump(self.master.custom_plugin_paths, f, ensure_ascii=False, indent=4)
            except OSError as e:
                print(f"File export error: {e}")

    def import_paths(self):
        filepath = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as f: data = json.load(f)
                self.master.custom_plugin_paths.update(data)
                self.master.save_settings()
                self.build_settings_ui() 
            except (OSError, json.JSONDecodeError) as e:
                print(f"File import error: {e}")

    def export_custom(self):
        custom_db_path = os.path.join(self.master.base_dir, "custom_plugins.json")
        if not os.path.exists(custom_db_path): return
        filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")])
        if filepath: 
            try:
                shutil.copy2(custom_db_path, filepath)
            except OSError as e:
                print(f"Error copying custom DB: {e}")

    def import_custom(self):
        filepath = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as f: data = json.load(f)
                if "plugins" not in data: return
                custom_db_path = os.path.join(self.master.base_dir, "custom_plugins.json")
                existing_data = {"plugins": []}
                if os.path.exists(custom_db_path):
                    with open(custom_db_path, 'r', encoding='utf-8') as f: existing_data = json.load(f)
                
                existing_names = {p["name"] for p in existing_data.get("plugins", [])}
                for p in data.get("plugins", []):
                    if p["name"] not in existing_names:
                        existing_data["plugins"].append(p)
                        existing_names.add(p["name"])
                
                with open(custom_db_path, 'w', encoding='utf-8') as f: json.dump(existing_data, f, ensure_ascii=False, indent=4)
                self.master.reload_custom_plugins() 
            except (OSError, json.JSONDecodeError) as e:
                print(f"Error importing custom plugins: {e}")

    def populate_logs(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        for entry in self.master.persistent_log_history: self.log_textbox.insert("end", entry.get(self.master.current_lang, entry["en"]) + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def append_log(self, text):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", text)
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def export_persistent_logs(self):
        if not self.master.persistent_log_history: return
        file_path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(f"--- AE Plugins Installer Persistent Logs ({self.master.CURRENT_VERSION}) ---\n\n")
                    for entry in self.master.persistent_log_history: f.write(entry.get(self.master.current_lang, entry["en"]) + "\n")
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
        
        self.CURRENT_VERSION = "Pre-release" 
        self.DB_URL = "https://raw.githubusercontent.com/Aks-iom/aksiom-installer-data/refs/heads/main/plugins.json"
        
        self.CHANGELOG_TEXT = {
            "ru": (
                "Версия Pre-release:\n"
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
                "Version Pre-release:\n"
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

        self.title("Ae plugins installer Pre-release")
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
        self.checkbox_widgets = {} 
        
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
        
        self.lang_dict = self.load_language_file()
        
        self.advanced_window = None 
        self.custom_install_path_var = ctk.StringVar()
        
        self.grid_columnconfigure(0, weight=0) 
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.icon_path = os.path.join(bundle_dir, "logo.ico")
        if os.path.exists(self.icon_path): self.iconbitmap(self.icon_path)

        self.plugins_data = []
        self.plugin_keywords = {}
        self.gdrive_file_ids = {}
        self.custom_data = {}

        self.load_plugins_database()
        self.create_widgets()
        
        self.version_var.trace_add("write", lambda *args: self.check_installed_plugins())
        self.check_installed_plugins()
        self.check_for_updates()

        self.settings_file = os.path.join(self.base_dir, "settings.json")
        self.custom_plugin_paths = self.load_settings()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._fix_russian_hotkeys()

    def load_language_file(self):
        lang_path = os.path.join(self.base_dir, "lang.json")
        default_dict = {
            "ru": {
                "title": "Ae plugins installer Pre-release", "version_lbl": "Выбор версии After Effects",
                "plugins_lbl": "Выбор плагинов", "select_all": "Выбрать все", "wait": "Ожидание...",
                "install_btn": "Установить выбранные", "log_lbl": "Журнал событий", "clear_log_btn": "Очистить логи",
                "export_log_btn": "Сохранить логи", "source_btn": "Источник", "complete": "Операция завершена",
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
                "warn_title": "Внимание", "warn_fields": "Поля 'Название' и типы файлов обязательны!",
                "err_title": "Ошибка", "err_exists": "Плагин с таким именем уже существует!",
                "select_file": "Выберите файл", "select_folder": "Выберите папку для",
                "target_folder": "Целевая папка", "setup_for": "Настройка для",
                "installing": "Установка", "exit_warn": "Установка не завершена. Выйти?",
                "force_install": "Принудительная установка",
                "rsmb_warn": "Мне не удалось сделать всю установку автоматически, поэтому вам придется нажать Extract самому (RSMB)."
            },
            "en": {
                "title": "Ae plugins Installer Pre-release", "version_lbl": "Select After Effects Version",
                "plugins_lbl": "Select Plugins", "select_all": "Select All", "wait": "Waiting...",
                "install_btn": "Install Selected", "log_lbl": "Event Log", "clear_log_btn": "Clear Logs",
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
                "warn_title": "Warning", "warn_fields": "'Name' and file types are required!",
                "err_title": "Error", "err_exists": "Plugin with this name already exists!",
                "select_file": "Select file", "select_folder": "Select folder for",
                "target_folder": "Target folder", "setup_for": "Setup for",
                "installing": "Installing", "exit_warn": "Installation not finished. Exit?",
                "force_install": "Force Install",
                "rsmb_warn": "I could not automate the whole installation, so you will have to click Extract yourself (RSMB)."
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

    def get_dynamic_paths(self, ae_version):
        custom_path = self.custom_install_path_var.get().strip()
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        
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
        custom_db_path = os.path.join(self.base_dir, "custom_plugins.json")
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

        self._parse_plugins_data(data, custom_db_path)

    def _update_db_in_background(self, local_db_path):
        try:
            req = urllib.request.Request(self.DB_URL, headers={'User-Agent': 'AksiomInstaller'})
            with urllib.request.urlopen(req, timeout=5) as response: new_data = json.loads(response.read().decode('utf-8'))
            with open(local_db_path, 'w', encoding='utf-8') as f: json.dump(new_data, f, ensure_ascii=False, indent=4)
        except Exception as e: 
            print(f"Background DB update failed: {e}")

    def _parse_plugins_data(self, data, custom_db_path):
        if data and "plugins" in data:
            for p in data["plugins"]:
                name = p["name"]
                self.plugins_data.append((name, p.get("version", "1.0"), p.get("bat_path", ""), p.get("needs_version", False), p.get("size", ""), p.get("md5", None)))
                self.plugin_keywords[name] = p.get("keywords", [name.lower().replace("_", " ").strip(), name.lower()])
                self.gdrive_file_ids[name] = p.get("gdrive_id", "")

        if os.path.exists(custom_db_path):
            try:
                with open(custom_db_path, 'r', encoding='utf-8') as f: c_data = json.load(f)
                for p in c_data.get("plugins", []):
                    name = p["name"]
                    self.plugins_data.append((name, p.get("version", "1.0"), "CUSTOM", False, p.get("size", ""), None))
                    self.plugin_keywords[name] = p.get("keywords", [name.lower().replace("_", " ").strip(), name.lower()])
                    self.gdrive_file_ids[name] = p.get("gdrive_id", "")
                    self.custom_data[name] = p
            except (OSError, json.JSONDecodeError) as e:
                print(f"Error parsing custom_plugins.json: {e}")
                
    def reload_custom_plugins(self):
        custom_db_path = os.path.join(self.base_dir, "custom_plugins.json")
        if not os.path.exists(custom_db_path): return
        try:
            with open(custom_db_path, 'r', encoding='utf-8') as f: c_data = json.load(f)
            for p in c_data.get("plugins", []):
                name = p["name"]
                if name not in self.custom_data:
                    self.plugins_data.append((name, p.get("version", "1.0"), "CUSTOM", False, p.get("size", ""), None))
                    self.plugin_keywords[name] = p.get("keywords", [name.lower().replace("_", " ").strip(), name.lower()])
                    self.gdrive_file_ids[name] = p.get("gdrive_id", "")
                    self.custom_data[name] = p
                    var = ctk.BooleanVar(value=False)
                    cb = ctk.CTkCheckBox(
                        self.scrollable_checkbox_frame, text=f"★ {name} [v{p.get('version', '1.0')}]  ({p.get('size', '')})", variable=var, 
                        command=lambda n=name, v=var: self.on_plugin_toggle(n, v),
                        font=self.font_main, checkbox_width=18, checkbox_height=18,
                        border_width=1, corner_radius=4, fg_color="#4CAF50", hover_color="#45a049"
                    )
                    cb.pack(anchor="w", pady=3, padx=5)
                    self.checkboxes.append((name, var))
                    self.checkbox_widgets[name] = cb 
            self.check_installed_plugins()
        except (OSError, json.JSONDecodeError) as e:
             print(f"Error reloading custom plugins: {e}")

    def create_widgets(self):
        left_width = 340
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])

        self.left_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.left_frame.grid(row=0, column=0, padx=(20, 10), pady=20, sticky="nsew")

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

        self.scrollable_checkbox_frame = ctk.CTkScrollableFrame(self.left_frame, width=left_width, height=230, fg_color="#1a1a1a", corner_radius=8)
        self.scrollable_checkbox_frame.pack(anchor="w", fill="x", pady=(0, 15))

        self.checkboxes = []
        self.select_all_var = ctk.BooleanVar(value=False)
        self.cb_select_all = ctk.CTkCheckBox(
            self.scrollable_checkbox_frame, text=t.get("select_all", "Select All"), variable=self.select_all_var, 
            command=self.toggle_all, font=self.font_main, fg_color=self.accent_color, hover_color=self.accent_hover
        )
        self.cb_select_all.pack(anchor="w", pady=(5, 5), padx=5)

        for plugin_name, version, bat_path, _, size, _ in self.plugins_data:
            var = ctk.BooleanVar(value=False)
            prefix = "★ " if bat_path == "CUSTOM" else ""
            custom_color = "#4CAF50" if bat_path == "CUSTOM" else "#6658cc"
            custom_hover = "#45a049" if bat_path == "CUSTOM" else "#5346a6"
            ver_text = "" if version == "1.0" else f" [v{version}]"
            
            cb = ctk.CTkCheckBox(
                self.scrollable_checkbox_frame, text=f"{prefix}{plugin_name}{ver_text}  ({size})", variable=var, 
                command=lambda n=plugin_name, v=var: self.on_plugin_toggle(n, v),
                font=self.font_main, fg_color=custom_color, hover_color=custom_hover, border_width=1
            )
            cb.pack(anchor="w", pady=3, padx=5)
            self.checkboxes.append((plugin_name, var))
            self.checkbox_widgets[plugin_name] = cb

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

        self.footer_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        self.footer_frame.pack(side="bottom", fill="x", pady=(10, 0)) 
        ctk.CTkButton(self.footer_frame, text="GitHub", font=("Calibri", 13, "underline"), width=0, height=20, fg_color="transparent", text_color="#888888", command=lambda: webbrowser.open("https://github.com/Aks-iom/Aks-iom-AE-Plugins-install-script")).pack(side="left", padx=(0, 10))
        ctk.CTkButton(self.footer_frame, text="Telegram", font=("Calibri", 13, "underline"), width=0, height=20, fg_color="transparent", text_color="#888888", command=lambda: webbrowser.open("https://t.me/AE_plugins_script")).pack(side="left", padx=(0, 10))
        ctk.CTkButton(self.footer_frame, text=t.get("source_btn", "Source"), font=("Calibri", 13, "underline"), width=0, height=20, fg_color="transparent", text_color="#888888", command=lambda: webbrowser.open("https://satvrn.li/windows")).pack(side="left")

        self.right_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.right_frame.grid(row=0, column=1, padx=(10, 20), pady=20, sticky="nsew")

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

        self.right_bottom_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.right_bottom_frame.pack(fill="x", pady=(10, 0))
        self.btn_advanced = ctk.CTkButton(self.right_bottom_frame, text=t.get("advanced_btn", "Advanced"), font=self.font_main, fg_color="#333333", hover_color="#444444", height=30, width=0, command=self.open_advanced_window)
        self.btn_advanced.pack(side="right")
        self.btn_clear_log = ctk.CTkButton(self.right_bottom_frame, text=t.get("clear_log_btn", "Clear"), font=self.font_main, fg_color="#333333", hover_color="#444444", height=30, width=0, command=self.clear_logs)
        self.btn_clear_log.pack(side="right", padx=(0, 10))

        self.target_y = None
        self._is_animating = False
        self.scrollable_checkbox_frame._mouse_wheel_all = self.smooth_wheel_event

    def filter_plugins(self, *args):
        query = self.search_var.get().lower()
        
        for name, cb in self.checkbox_widgets.items():
            cb.pack_forget()
            
        for name, cb in self.checkbox_widgets.items():
            if query in name.lower() or query in cb.cget("text").lower():
                cb.pack(anchor="w", pady=3, padx=5)

    def open_advanced_window(self):
        try:
            if self.advanced_window is None or not self.advanced_window.winfo_exists(): 
                self.advanced_window = AdvancedWindow(self)
            else:
                self.advanced_window.deiconify()  
                self.advanced_window.focus() 
        except Exception: 
            self.advanced_window = AdvancedWindow(self)     

    def toggle_language(self):
        self.current_lang = "en" if self.current_lang == "ru" else "ru"
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
        
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
        self.btn_advanced.configure(text=t["advanced_btn"])
        self.btn_lang.configure(text="RU" if self.current_lang == "en" else "EN")

        if hasattr(self, 'btn_update'): self.btn_update.configure(text=self.update_btn_texts[self.current_lang])

        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        for entry in self.log_history: self.log_textbox.insert("end", entry.get(self.current_lang, entry["en"]) + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

        if self.advanced_window and self.advanced_window.winfo_exists():
            aw = self.advanced_window
            aw.title(t["advanced_btn"])
            aw.btn_tab_changelog.configure(text=t["tab_changelog"])
            aw.btn_tab_logs.configure(text=t["tab_logs"])
            aw.btn_tab_custom.configure(text=t["tab_custom"])
            aw.btn_tab_settings.configure(text=t["tab_settings"])
            aw.btn_tab_sync.configure(text=t.get("tab_sync", "Export / Import"))
            aw.btn_tab_uninstall.configure(text=t.get("tab_uninstall", "Uninstall"))
            
            aw.lbl_settings_title.configure(text=t["settings_title"])
            aw.lbl_custom_title.configure(text=t["custom_title"])
            aw.lbl_un_title.configure(text=t.get("un_title", "Uninstall Plugins"))
            aw.lbl_un_desc.configure(text=t.get("un_desc", ""))
            
            aw.entry_c_name.configure(placeholder_text=t["c_name_ph"])
            aw.btn_add_custom.configure(text=t["custom_add_btn"])

            if hasattr(aw, 'lbl_sync_title'): aw.lbl_sync_title.configure(text=t.get("sync_title"))
            if hasattr(aw, 'lbl_sync_paths'): aw.lbl_sync_paths.configure(text=t.get("sync_paths"))
            if hasattr(aw, 'btn_export_paths'): aw.btn_export_paths.configure(text=t.get("export_btn"))
            if hasattr(aw, 'btn_import_paths'): aw.btn_import_paths.configure(text=t.get("import_btn"))
            if hasattr(aw, 'lbl_sync_custom'): aw.lbl_sync_custom.configure(text=t.get("sync_custom"))
            if hasattr(aw, 'btn_export_custom'): aw.btn_export_custom.configure(text=t.get("export_btn"))
            if hasattr(aw, 'btn_import_custom'): aw.btn_import_custom.configure(text=t.get("import_btn"))
            if hasattr(aw, 'lbl_sync_warn'): aw.lbl_sync_warn.configure(text=t.get("sync_warn"))
            
            if hasattr(aw, 'btn_export'): aw.btn_export.configure(text=t.get("export_log_btn", "Export Logs"))
            if hasattr(aw, 'btn_reset_all'): aw.btn_reset_all.configure(text=t.get("reset_all", "Reset All"))
            if hasattr(aw, 'lbl_type'): aw.lbl_type.configure(text=t.get("plugin_type", "File Types"))

            aw.update_path_visibility()

            aw.changelog_text.configure(state="normal")
            aw.changelog_text.delete("1.0", "end")
            aw.changelog_text.insert("1.0", self.CHANGELOG_TEXT[self.current_lang])
            aw.changelog_text.configure(state="disabled")
            if aw.frame_uninstall.winfo_ismapped(): aw.build_uninstall_ui()
        
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

        if self.advanced_window and self.advanced_window.winfo_exists(): self.advanced_window.append_log(msg + "\n")

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

        if self.advanced_window and self.advanced_window.winfo_exists(): 
            self.advanced_window.update_last_log(msg)

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
            if "pre-release" in current.lower() or current.lower() == "pre-release":
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
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        pd = os.environ.get("ProgramData", r"C:\ProgramData")

        dirs = [
            os.path.join(pf, "BorisFX", "ContinuumAE", "14", "lib"),
            os.path.join(pf, "BorisFX"),
            os.path.join(pf, "Adobe"),
            os.path.join(pf, "Maxon"),
            os.path.join(pf, "GenArts"),
            os.path.join(pf, "Adobe", f"Adobe After Effects {ae_version}", "Support Files", "Plug-ins", "Plugins Everything"),
            os.path.join(pf, "Adobe", f"Adobe After Effects {ae_version}", "Support Files", "Plug-ins", "VideoCopilot"),
            os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore"),
            os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore", "RSMB"),
            os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore", "Twixtor8AE"),
            os.path.join(pf86, "Common Files", "Adobe", "CEP", "extensions"),
            pd
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

    def _fast_search(self, directory, plugin_name, keywords, max_depth=2, current_depth=0):
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
            for p in self.custom_data[plugin_name].get("custom_target_paths", {}).values():
                if p:
                    search_dirs.append(p)
                    has_custom = True
                    
        if not has_custom: search_dirs = self.get_search_dirs(ae_version)
        keywords = self.plugin_keywords.get(plugin_name, [plugin_name.lower()])
        
        for d in set(d for d in search_dirs if os.path.exists(d)):
            if self._fast_search(d, plugin_name, keywords): return True
            
        pd = os.environ.get("ProgramData", r"C:\ProgramData")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        
        if not has_custom and plugin_name == "Sapphire" and glob.glob(os.path.join(pd, "GenArts", "rlm", "*.lic")): 
            return True
            
        if not has_custom and plugin_name == "RSMB":
            rev_path = os.path.join(pf, "Adobe", "Common", "Plug-ins", "7.0", "MediaCore", "REVisionEffects")
            if os.path.exists(rev_path):
                if any("rsmb" in f.lower() for f in os.listdir(rev_path)):
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
        
        # --- ДОБАВЬ ЭТОТ БЛОК ---
        if state: # Если поставили галочку "Выбрать все"
            ru_msg = self.lang_dict.get("ru", {}).get("rsmb_warn", "Мне не удалось сделать всю установку автоматически, поэтому вам придется нажать Extract самому (RSMB).")
            en_msg = self.lang_dict.get("en", {}).get("rsmb_warn", "I could not automate the whole installation, so you will have to click Extract yourself (RSMB).")
            self.log(f"⚠️ [ВНИМАНИЕ] {ru_msg}", f"⚠️ [WARNING] {en_msg}")
        # --------------------------

    def on_plugin_toggle(self, plugin_name, var):
        self.select_all_var.set(all(var.get() for _, var in self.checkboxes))
        
        # --- ДОБАВЬ ЭТОТ БЛОК ---
        if plugin_name == "RSMB" and var.get():
            ru_msg = self.lang_dict.get("ru", {}).get("rsmb_warn", "Мне не удалось сделать всю установку автоматически, поэтому вам придется нажать Extract самому (RSMB).")
            en_msg = self.lang_dict.get("en", {}).get("rsmb_warn", "I could not automate the whole installation, so you will have to click Extract yourself (RSMB).")
            self.log(f"⚠️ [ВНИМАНИЕ] {ru_msg}", f"⚠️ [WARNING] {en_msg}")
        # --------------------------

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

        # Логика для RSMB: предупреждение и перемещение в начало очереди
        if "RSMB" in selected:
            selected.remove("RSMB")
            selected.insert(0, "RSMB")  # Ставим RSMB на 1-е место
        self.btn_install.configure(state="disabled")
        self.log(
            f"\n{'='*50}\n🚀 УСТАНОВКА AFTER EFFECTS {full_ae_version}\n{'='*50}",
            f"\n{'='*50}\n🚀 INSTALLING AFTER EFFECTS {full_ae_version}\n{'='*50}"
        )

        custom_install_path = self.custom_install_path_var.get().strip()
        threading.Thread(target=self.run_install_process, args=(full_ae_version, selected, custom_install_path), daemon=True).start()

    def execute_native_install(self, plugin_name, ae_version, src_dir):
        plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
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
            
        elif plugin_name == "RSMB":
            exe_files = glob.glob(os.path.join(src_dir, "*.exe"))
            if exe_files:
                installer_path = exe_files[0]
                self.log("[*] Запуск установщика RSMB. Пожалуйста, пройдите установку в появившемся окне...", "[*] Starting RSMB installer. Please complete the setup in the window...")
                # Обычный запуск без скрытия окна (без CREATE_NO_WINDOW и /SILENT)
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
                
        elif plugin_name == "RedGiant":
            subprocess.run([os.path.join(src_dir, "1_Maxon.exe"), "--mode", "unattended", "--unattendedmodeui", "minimal"], check=True, creationflags=CREATE_NO_WINDOW)
            subprocess.run([os.path.join(src_dir, "2_RedGiant.exe"), "--mode", "unattended", "--unattendedmodeui", "minimal"], check=True, creationflags=CREATE_NO_WINDOW)
            subprocess.run([os.path.join(src_dir, "3_Unlocker.exe"), "/SILENT"], check=True, creationflags=CREATE_NO_WINDOW)
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
        exe_installers = ["BCC", "Mocha_Pro", "Sapphire", "RedGiant", "RSMB"]
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
        
        if plugin_name in exe_installers:
            messagebox.showwarning(t.get("warn_title", "Warning"), t.get("un_warn_exe", "Uninstall this using Windows Control Panel."))
            return False

        try:
            if plugin_name in self.custom_data:
                c_files = self.custom_data[plugin_name].get("custom_files", {})
                
                plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)
                custom_install_path = self.custom_install_path_var.get().strip()

                for t_id, f_info in c_files.items():
                    target_dir = f_info.get("target_path", "")
                    
                    if not target_dir:
                        if t_id == "zip":
                            target_dir = custom_install_path if custom_install_path else os.path.join(plugins_dir, plugin_name)
                        elif t_id in ["aex", "exe"]:
                            target_dir = plugins_dir
                        elif t_id == "jsx":
                            target_dir = scripts_dir

                    filename = f_info.get("filename")
                    
                    if t_id == "zip":
                        if target_dir and os.path.exists(target_dir):
                            folder_name = os.path.basename(os.path.normpath(target_dir))
                            if plugin_name.lower() == folder_name.lower():
                                shutil.rmtree(target_dir, ignore_errors=True)
                    elif target_dir and filename:
                        full_path = os.path.join(target_dir, filename)
                        if os.path.exists(full_path):
                            if os.path.isdir(full_path): shutil.rmtree(full_path, ignore_errors=True)
                            else: os.remove(full_path)
                return True
            
            search_dirs = []
            custom_main_path = self.custom_plugin_paths.get(plugin_name, "").strip()
            if custom_main_path: search_dirs.append(self.resolve_target_path(plugin_name, "", ae_version))
            else: search_dirs = self.get_search_dirs(ae_version)
            
            keywords = self.plugin_keywords.get(plugin_name, [plugin_name.lower()])
            deleted_something = False

            for d in set(d for d in search_dirs if os.path.exists(d)):
                try:
                    with os.scandir(d) as it:
                        for entry in it:
                            name_lower = entry.name.lower()
                            for kw in keywords:
                                if kw.lower() in name_lower:
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

    def run_install_process(self, ae_version, selected_plugins, custom_install_path):
        t = self.lang_dict.get(self.current_lang, self.lang_dict["en"])
        try:
            total = len(selected_plugins)
            native_plugins = [p[0] for p in self.plugins_data]
            
            for index, plugin_name in enumerate(selected_plugins):
                plugin_info = next((p for p in self.plugins_data if p[0] == plugin_name), None)
                if not plugin_info: continue

                _, _, bat_path, needs_version, _, expected_md5 = plugin_info
                is_custom = plugin_name in self.custom_data
                
                self.after(0, self._update_progress_ui, f"{t.get('installing', 'Installing')}: {plugin_name}...", index / total)
                self.log(
                    f"\n----------------------------------------\n📦 ПЛАГИН: {plugin_name}\n----------------------------------------",
                    f"\n----------------------------------------\n📦 PLUGIN: {plugin_name}\n----------------------------------------"
                )

                if is_custom:
                    c_files = self.custom_data[plugin_name].get("custom_files", {})
                    plugins_dir, scripts_dir = self.get_dynamic_paths(ae_version)

                    for t_id, f_info in c_files.items():
                        c_source, c_filename = f_info.get("source"), f_info.get("filename")
                        target_file_path = os.path.join(self.base_dir, c_filename)
                        c_target_path = f_info.get("target_path", "")

                        if c_source == "gdrive":
                            if not os.path.exists(target_file_path):
                               if not self.download_from_gdrive(f_info.get("gdrive_id"), target_file_path, plugin_name, index, total): continue
                            else:
                             self.log(f"[*] Файл .{t_id} найден в локальном кэше.", f"[*] .{t_id} file found in local cache.")
                            
                        if not os.path.exists(target_file_path): 
                            self.log(f"❌ Ошибка: Локальный файл {c_filename} не найден в кэше! Добавьте плагин заново.", 
                                 f"❌ Error: Local file {c_filename} missing from cache! Re-add the plugin.")
                            continue

                        try:
                            if t_id == "zip":
                                self.log("[*] Распаковка .zip...", "[*] Extracting .zip...")
                                extract_target = c_target_path if c_target_path else (custom_install_path if custom_install_path else os.path.join(plugins_dir, plugin_name))
                                os.makedirs(extract_target, exist_ok=True)
                                with zipfile.ZipFile(target_file_path, 'r') as zip_ref: zip_ref.extractall(extract_target)
                            elif t_id == "exe": 
                                self.log("[*] Запуск установщика .exe...", "[*] Running .exe installer...")
                                subprocess.run([target_file_path], check=True)
                            elif t_id == "aex":
                                self.log("[*] Копирование .aex...", "[*] Copying .aex...")
                                target_dir = c_target_path if c_target_path else plugins_dir
                                os.makedirs(target_dir, exist_ok=True); shutil.copy2(target_file_path, target_dir)
                            elif t_id == "jsx":
                                self.log("[*] Копирование скрипта...", "[*] Copying script...")
                                target_dir = c_target_path if c_target_path else scripts_dir
                                os.makedirs(target_dir, exist_ok=True); shutil.copy2(target_file_path, target_dir)
                            elif t_id == "reg":
                                self.log("[*] Применение файла реестра...", "[*] Applying registry file...")
                                ctypes.windll.shell32.ShellExecuteW(None, "runas", "reg.exe", f'import "{target_file_path}"', None, 0)
                                time.sleep(1) 
                            self.log(f"✅ Файл .{t_id} успешно установлен.", f"✅ .{t_id} file successfully installed.")
                        except zipfile.BadZipFile as e:
                            self.log(f"❌ Архив {c_filename} поврежден или не является ZIP-файлом: {e}", f"❌ Archive {c_filename} is corrupted or not a ZIP file: {e}")
                        except (OSError, PermissionError) as e: 
                            self.log(f"❌ Ошибка копирования или доступа {t_id}: {e}", f"❌ Error copying or accessing {t_id}: {e}")
                        except subprocess.CalledProcessError as e:
                            self.log(f"❌ Ошибка выполнения установщика {t_id}: {e}", f"❌ Error executing {t_id} installer: {e}")
                        except Exception as e:
                            self.log(f"❌ Непредвиденная ошибка при распаковке {t_id}: {e}", f"❌ Unexpected error extracting {t_id}: {e}")
                else:
                    plugin_src_dir = os.path.dirname(os.path.join(self.base_dir, bat_path))
                    zip_path = os.path.join(self.base_dir, f"{plugin_name}.zip")
                    
                    if not os.path.exists(plugin_src_dir):
                        if not self.download_from_gdrive(self.gdrive_file_ids.get(plugin_name), zip_path, plugin_name, index, total): continue
                        if not self.verify_archive_integrity(zip_path, expected_md5): continue
                        
                        self.log("[*] Распаковка файлов...", "[*] Extracting files...")
                        try:
                            with zipfile.ZipFile(zip_path, 'r') as zip_ref: zip_ref.extractall(self.base_dir)
                            self.log("[+] Распаковка завершена.", "[+] Extraction complete.")
                        except zipfile.BadZipFile as e: 
                            self.log(f"❌ Архив поврежден: {e}", f"❌ Archive corrupted: {e}")
                            continue
                        except OSError as e:
                            self.log(f"❌ Ошибка распаковки архива: {e}", f"❌ Error extracting archive: {e}")
                            continue
                        finally:
                            if os.path.exists(zip_path):
                                try: os.remove(zip_path)
                                except OSError: pass
                    else:
                        self.log("[*] Файлы найдены в кэше. Скачивание пропущено.", "[*] Files found in cache. Download skipped.")

                    try:
                        if plugin_name in native_plugins: 
                            self.log(f"[*] Выполнение установки...", "[*] Executing installation...")
                            self.execute_native_install(plugin_name, ae_version, plugin_src_dir)
                            self.log(f"✅ {plugin_name} успешно установлен.", f"✅ {plugin_name} successfully installed.")
                    except OSError as e:
                         self.log(f"❌ Сбой файловой системы или отказ в доступе: {str(e)}", f"❌ File system failure or access denied: {str(e)}")
                    except Exception as e:
                         self.log(f"❌ Критический сбой установки {plugin_name}: {str(e)}", f"❌ Critical installation failure for {plugin_name}: {str(e)}")

                self.after(0, self._update_progress_ui, f"{t.get('complete', 'Complete')}: {plugin_name}", (index + 1) / total)

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