# Точечные патчи (справочник diff-фрагментов)

Все эти изменения **уже применены** в готовых файлах в `fixed/`.
Этот файл оставлен как справочник для тех, кто хочет применить правки
вручную в свою копию (через `git apply` или редактор) вместо того,
чтобы заменять файлы целиком.

Если ты заменил файлы из `fixed/` — этот документ можно игнорировать.

================================================================================
## main_window.py
================================================================================

### [AKSIOM-FIX #6] Ограничить рост persistent_log_history

В `__init__` (строки ~601-602) ЗАМЕНИТЬ:

```python
self.log_history: list[dict[str, str]] = []
self.persistent_log_history: list[dict[str, str]] = []
```

НА:

```python
from collections import deque
self.log_history: list[dict[str, str]] = []
# [AKSIOM-FIX #6] Ограничиваем рост — иначе при долгой работе течёт память
self.persistent_log_history: deque[dict[str, str]] = deque(maxlen=10000)
```

И в `clear_logs` (строка ~1342) добавить очистку:

```python
def clear_logs(self) -> None:
    self.log_history.clear()
    # [AKSIOM-FIX #6] Также чистим persistent — оставлять смысла мало
    self.persistent_log_history.clear()
    widget = ...
```

`deque` поддерживает `.append`, `.clear`, `.__getitem__` — drop-in
для существующего кода.

--------------------------------------------------------------------------------

### [AKSIOM-FIX #18] Вынести парсинг custom-плагинов из `_parse_plugins_data`
###                  и `reload_custom_plugins` в один helper

Добавить новый метод (рядом с `_parse_plugins_data`):

```python
def _load_custom_plugins_from_dir(self) -> None:
    """[AKSIOM-FIX #18] Единая точка парсинга custom-плагинов.
    Вызывается и из _parse_plugins_data, и из reload_custom_plugins."""
    if not os.path.exists(self.custom_configs_dir):
        return
    for filename in os.listdir(self.custom_configs_dir):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(self.custom_configs_dir, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                c_data = json.load(f)
            for p in c_data.get("plugins", []):
                name = p["name"]
                self.plugins_data.append((
                    name,
                    p.get("version", "1.0"),
                    "CUSTOM",
                    False,
                    p.get("size", ""),
                    None,
                ))
                base_kw = name.lower()
                default_kws = [
                    base_kw.replace("_", " ").strip(),
                    base_kw,
                    base_kw.replace("_", ""),
                ]
                json_kws = list(p.get("keywords", []))
                # [AKSIOM-FIX #24] Дедуп с сохранением порядка
                self.plugin_keywords[name] = list(dict.fromkeys(default_kws + json_kws))
                self.gdrive_file_ids[name] = p.get("gdrive_id", "")
                self.custom_data[name] = p
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Error parsing {filename}: {exc}")
```

Затем в `_parse_plugins_data` УДАЛИТЬ блок строк 968-1000 (Пользовательские
плагины из custom_configs ...) и заменить вызовом:

```python
self._load_custom_plugins_from_dir()
```

В `reload_custom_plugins` УДАЛИТЬ блок строк 1053-1084 (Перечитываем
custom_configs ...) и заменить тем же вызовом:

```python
self._load_custom_plugins_from_dir()
```

--------------------------------------------------------------------------------

### [AKSIOM-FIX #24] Сохранить порядок keywords

В `_parse_plugins_data` (строка 964) ЗАМЕНИТЬ:

```python
self.plugin_keywords[name] = list(set(default_kws + json_kws))
```

НА:

```python
# [AKSIOM-FIX #24] dict.fromkeys сохраняет порядок (Python 3.7+)
self.plugin_keywords[name] = list(dict.fromkeys(default_kws + json_kws))
```

================================================================================
## plugin_checker.py
================================================================================

### [AKSIOM-FIX #14] Ограничить глубину `_has_relevant_files`

В классе PluginCheckerMixin ЗАМЕНИТЬ метод `_has_relevant_files`:

```python
def _has_relevant_files(self, directory: str, max_depth: int = 4) -> bool:
    """
    [AKSIOM-FIX #14] Ограниченный по глубине обход вместо полного os.walk.
    Возвращает True при первом же релевантном файле.
    """
    plugin_exts = (
        ".aex", ".jsx", ".jsxbin", ".dll", ".exe",
        ".prm", ".lic", ".zxp", ".plugin",
    )
    return self._scan_for_relevant_recursive(directory, plugin_exts, max_depth, 0)


def _scan_for_relevant_recursive(
    self, directory: str, exts: tuple, max_depth: int, depth: int
) -> bool:
    if depth > max_depth:
        return False
    try:
        with os.scandir(directory) as it:
            for entry in it:
                try:
                    if entry.is_file() and entry.name.lower().endswith(exts):
                        return True
                    if entry.is_dir():
                        if self._scan_for_relevant_recursive(
                            entry.path, exts, max_depth, depth + 1
                        ):
                            return True
                except OSError:
                    continue
    except (PermissionError, OSError):
        pass
    return False
```

================================================================================
## advanced_frame.py
================================================================================

### [AKSIOM-FIX #13] MamboClickFilter не должен пересоздавать Sound на каждый клик

ЗАМЕНИТЬ класс `MamboClickFilter` (строки 86-97):

```python
class MamboClickFilter(QObject):
    """[AKSIOM-FIX #13] Sound кэшируется — не парсим WAV на каждый клик."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sound = None
        if HAS_PYGAME:
            try:
                wav_path = get_resource_path("mambo_assets/mambo.wav")
                if os.path.exists(wav_path):
                    self._sound = pygame.mixer.Sound(wav_path)
            except Exception:
                self._sound = None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and self._sound is not None:
            try:
                self._sound.play()
            except Exception:
                pass
        return False
```

И в `AdvancedFrame.__init__` (строка 127):

```python
self.mambo_filter = MamboClickFilter(self)
```

Уже передаём self как parent — корректно.

--------------------------------------------------------------------------------

### [AKSIOM-FIX #20] clear_app_cache: один проход вместо двух

ЗАМЕНИТЬ метод `clear_app_cache` (строки 1343-1372):

```python
def clear_app_cache(self) -> None:
    t = self._t()
    is_ru = self.app.current_lang == "ru"
    msg = ("Удалить все временные файлы и скачанные архивы?\n"
           "(Ваши настройки и кастомные плагины сохранятся)" if is_ru else
           "Delete all temporary files and downloaded archives?\n"
           "(Settings and custom plugins will be kept)")
    reply = QMessageBox.question(self, t.get("warn_title", "Warning"), msg)
    if reply != QMessageBox.StandardButton.Yes:
        return

    keep_files = {"app_config.json", "settings.json", "plugins.json", "lang.json"}
    keep_dirs = {"custom_configs", "installed"}  # манифесты тоже не сносим
    deleted_size = 0

    def _dir_size(path: str) -> int:
        """[AKSIOM-FIX #20] Один проход — считаем и удаляем за раз позже."""
        total = 0
        try:
            for entry in os.scandir(path):
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += _dir_size(entry.path)
                except OSError:
                    continue
        except OSError:
            pass
        return total

    try:
        for item in os.listdir(self.app.cache_dir):
            item_path = os.path.join(self.app.cache_dir, item)
            try:
                if os.path.isfile(item_path):
                    if item not in keep_files:
                        deleted_size += os.path.getsize(item_path)
                        os.remove(item_path)
                elif os.path.isdir(item_path):
                    if item not in keep_dirs:
                        deleted_size += _dir_size(item_path)
                        shutil.rmtree(item_path, ignore_errors=True)
            except OSError:
                continue
        mb = deleted_size / (1024 * 1024)
        success = (f"Кэш успешно очищен!\nОсвобождено: {mb:.2f} МБ" if is_ru else
                   f"Cache cleared!\nFreed: {mb:.2f} MB")
        QMessageBox.information(
            self, "Инфо" if is_ru else "Info", success,
        )
    except Exception as exc:
        QMessageBox.critical(
            self,
            "Ошибка" if is_ru else "Error",
            f"Произошла ошибка:\n{exc}",
        )
```

Изменения:
1. Один обход через `os.scandir` (быстрее `os.walk`).
2. `installed/` (манифесты) добавлен в `keep_dirs` — иначе при чистке кэша
   мы теряем информацию об установленных плагинах.
3. Корректная обработка `OSError` поэлементно — один сбойный файл не
   ломает весь процесс.

================================================================================
## Дополнительный файл core/installer/__init__.py
================================================================================

В export добавлен ARTIFACT_REG_KEY и SOURCE_*  — пригодится для тестов и
плагинов, которые захотят регистрировать reg_key артефакты:

```python
from core.installer.manifest import (
    InstalledManifest,
    ARTIFACT_FILE,
    ARTIFACT_DIR,
    ARTIFACT_REG_VALUE,
    ARTIFACT_REG_KEY,        # добавлено
    ARTIFACT_EXE_INSTALL,
    SOURCE_MANAGED,          # добавлено
    SOURCE_LEGACY,           # добавлено
)
```
