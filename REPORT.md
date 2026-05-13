# Отчёт по анализу кода Aksiom Installer

Проверены модули `installer_logic.py`, всё ядро `core/installer/*`, бегло — `main_window.py`, `plugin_checker.py`, `install_tab.py`, `advanced_frame.py`. Исправленные файлы лежат в папке `fixed/` рядом с этим отчётом.

Категории:
- 🔴 **Критично** — может привести к потере данных, крашу, неправильной работе
- 🟡 **Серьёзно** — баги поведения, утечки, гонки
- 🟢 **Оптимизация / качество** — производительность, читаемость, дубли

---

## 🔴 КРИТИЧНЫЕ БАГИ

### 1. Потеря пользовательских данных при rollback в `replace`-режиме `CopyDirStep`

**Файл:** `core/installer/steps/copy_dir.py`, строки 99–100

После успешного копирования бэкап целевой папки удаляется. Но если **последующий** шаг в pipeline упадёт, транзакция позовёт `remove_artifact` для `ARTIFACT_DIR`, который сделает `rmtree` целевой папки. **Бэкапа уже нет** — пользовательские файлы безвозвратно потеряны.

Сценарий:
1. Плагин устанавливается с `mode: "replace"` в `C:\Plugins\X` (там были файлы пользователя).
2. `CopyDirStep` создаёт бэкап `X.aksiom_bak`, копирует, удаляет бэкап → success.
3. Следующий шаг (`copy_file`, `import_reg`, что угодно) падает.
4. Транзакция откатывает: `rmtree(C:\Plugins\X)`. Старые файлы пользователя пропали.

**Фикс:** не удалять бэкап на месте. Передавать его в transaction отдельным «cleanup-on-commit» хуком, либо сохранять путь бэкапа в `extra` артефакта и удалять при `commit()`. Самый простой вариант — отказаться от replace-семантики в манифесте и реализовывать «replace» как `delete` + `copy_dir(merge)` на уровне манифеста.

В патче: добавлен механизм `pending_backups` в `InstallTransaction`. Бэкапы удаляются только в `commit()`; при rollback — восстанавливаются.

### 2. `ARTIFACT_REG_KEY.remove_artifact` не удаляет ключ

**Файл:** `core/installer/manifest.py`, строки 118–136

```python
hive_str, key, _ = _split_reg_path(artifact.path + "\\__dummy")
```

`_split_reg_path` принимает строку вида `HIVE\path\to\value` и делит её на `(hive, key, name)`, где `name` — последний сегмент. Хак с добавлением `\__dummy` нужен, чтобы `name` стал `__dummy`, а в `key` попало то, что нужно удалить. **Но если `artifact.path` оканчивается на `\` или содержит лишние сегменты — splitter сработает неверно.**

Проблема глубже: `winreg.DeleteKey` удаляет только пустой ключ (без подключей). Для рекурсивного удаления нужно `winreg.DeleteKeyEx` или ручной обход. Нигде не используется такой артефакт — `set_reg_value` создаёт `ARTIFACT_REG_VALUE`, не `REG_KEY` — так что код мёртвый, но если кто-то добавит шаг создания ключа, оно молча сломается.

**Фикс:** заменить хак на нормальный путь без `__dummy`, использовать `DeleteKeyEx`, добавить рекурсивное удаление подключей.

### 3. Не обрабатывается `subprocess.CalledProcessError` в `execute_native_install` для Mocha_Pro / Universe / Trapcode / MBS

**Файл:** `installer_logic.py`, строки 384, 593, 606, 619

`subprocess.run(..., check=True)` без `try` — если инсталлер вернёт ненулевой код (например, 3010 «требуется перезагрузка» — это **успех** для Windows-инсталлеров на InstallShield/Inno Setup), весь процесс упадёт исключением, плагин будет помечен как незавершённый. Для Sapphire (строка 444) обработка есть, для Mocha_Pro и группы Universe/Trapcode/MBS — нет.

**Фикс:** добавить try/except или передать `check=False` и явно проверять returncode с whitelisting кодов 0 и 3010.

### 4. Гонка между `start_installation` и фоновым download_task

**Файл:** `installer_logic.py`, строки 907–910

```python
if selected_plugins:
    threading.Thread(target=download_task, args=(selected_plugins[0], 0), daemon=True).start()
```

И сразу после в цикле:
```python
if index + 1 < total:
    next_plugin = selected_plugins[index + 1]
    threading.Thread(target=download_task, args=(next_plugin, index + 1), daemon=True).start()
```

Логика «параллельной подкачки» работает, **НО**: `_GDOWN_STDERR_LOCK` подменяет `sys.stderr` глобально. Когда два потока пытаются скачивать одновременно (первый запущен в строке 909, второй стартует в 922 как только первый плагин начал устанавливаться), они борются за один лок, и `gdown` будет писать прогресс по очереди. Это не баг, но **планируемой параллельной загрузки нет** — из-за лока всё фактически последовательно. Просто download N+1 начинается в момент, когда install N запущен — это не потоковая загрузка, а sequential. Стоит убрать иллюзию параллелизма (комментарий `# параллельная подкачка следующего`) или сделать честно через очередь.

Бóльшая опасность: если `download_task` для плагина N падает раньше, чем главный поток дошёл до `download_events[plugin_name].wait()` (строка 918), флаг `set()` уже был. Это работает. Но если в строке 909 стартовый поток упал ещё до старта for-цикла... Ловим в `try/except`, но при исключении `download_results[name] = False`, и в `finally` всё равно `set()` — корректно.

Однако `download_task` мутирует `download_results: dict[str, bool]` без блокировки. На CPython GIL спасает простые dict-присваивания, но в общем случае стоит хотя бы пометить это в комментарии или вынести в `concurrent.futures`.

### 5. `subprocess.Popen` без `creationflags=CREATE_NO_WINDOW` в `run_maxon_activator`

**Файл:** `installer_logic.py`, строка 779

```python
subprocess.Popen([exe_path])
```

Для всех остальных вызовов используется `CREATE_NO_WINDOW`. Здесь — нет. На Windows у пользователя может вылететь чёрное консольное окно перед окном инсталлера, что некрасиво. Если активатор использует stdout — он может упасть, потому что у Popen нет stdout/stderr дескрипторов. Для GUI-приложения — это норма, но для CLI-активатора может быть проблемой.

**Фикс:** оставить открытие окна (это GUI-инсталлер), но добавить `creationflags=0` явно и `stdout=subprocess.DEVNULL` для безопасности. Либо ничего не менять, **но добавить try/except FileNotFoundError**, который сейчас ловится только OSError (FileNotFoundError — подкласс OSError, ок).

Реальный баг: если `exe_path` указывает на несуществующий файл (физически удалён между `find_maxon_activator` и `run_maxon_activator`), `Popen` бросит `FileNotFoundError`, который ловится, **но** дальше в строках 786-790 идёт код с `tmpl.format(plugin=plugin_name)` — он не выполнится, потому что мы уже вернулись из except. Однако сообщение об успехе не вернётся — это ОК, мы в except возвращаем False. То есть фактически кода ОК.

### 6. Утечка лога / `persistent_log_history` растёт неограниченно

**Файл:** `main_window.py`, `install_tab.py`

`persistent_log_history` никогда не очищается (`clear_logs` чистит только `log_history`, не `persistent_log_history`). При длительной работе и многих установках память течёт. На каждое сообщение храним 2 строки (ru/en) в двух списках.

**Фикс:** ограничить `persistent_log_history` через `collections.deque(maxlen=10000)` или периодически тримминг.

### 7. Проблема с `subprocess.run([installer_path], check=True)` для RSMB

**Файл:** `installer_logic.py`, строка 430

Здесь нет `creationflags=CREATE_NO_WINDOW`, но это намеренно (комментарий выше: «Пожалуйста, пройдите установку в появившемся окне»). НО — `check=True` означает, что если пользователь нажмёт «Cancel» в инсталлере (returncode != 0), весь процесс рухнет с CalledProcessError. Лучше `check=False` с осмысленным сообщением.

---

## 🟡 СЕРЬЁЗНЫЕ ПРОБЛЕМЫ

### 8. Кэширование `_lookup_native_plugin_meta` отсутствует

**Файл:** `installer_logic.py`, строки 707–722

Метод читает `plugins.json` с диска **при каждом вызове**. В цикле установки 10 плагинов → 10 раз парсится JSON. Плюс каждый вызов `is_plugin_installed` (а их много на старте — `check_installed_plugins` итерирует по всем плагинам) → ещё столько же.

Файл небольшой, но это IO + JSON parse, который можно сделать один раз. На SSD не критично, на HDD заметно тормозит UI на старте.

**Фикс:** кэшировать результат до изменения файла на диске (mtime-based). См. патч.

### 9. `lambda` в default-значении dataclass-поля `InstallContext.logger`

**Файл:** `core/installer/context.py`, строка 112

```python
logger: Callable[[str, str], None] = lambda _ru, _en: None
```

Технически работает — лямбда создаётся при определении класса и шарится между всеми инстансами (она stateless, так что норм). НО `dataclass` ругается на mutable defaults. На Python 3.11+ это даёт `ValueError: mutable default ... is not allowed: use default_factory` — пока не падает только потому, что lambda не считается mutable. На будущее это unsafe.

**Фикс:** использовать `default=None` + ленивая инициализация, или `field(default_factory=lambda: lambda r, e: None)`. См. патч.

### 10. `os.path.exists` гонки в `verify_archive_integrity`

**Файл:** `installer_logic.py`, строки 196–211

Окей логика, но:
- `print(f"MD5 read error: {exc}")` — лог в stdout, а не через `self.log()`. Пользователь не увидит ошибку. То же в `print(f"File system error...")`.
- При `BadZipFile` — возвращаем False **без удаления битого zip**. На следующем вызове `_ensure_downloaded` опять увидит, что zip есть, попробует verify, опять False, опять скачать → но `os.path.exists(zip_path)` true, `verify_archive_integrity` false → **попадаем в ветку перескачивания**. Значит, OK, но zip перезапишется через `gdown`. Если gdown сломается — у нас останется битый zip навсегда.

**Фикс:** удалять битый zip в `verify_archive_integrity`, заменить `print` на `self.log` (но миксин — здесь нет `self.log` без верхнего класса, поэтому можно прокинуть логгер).

### 11. В `if_step._eval_condition` баг с пустым negate

**Файл:** `core/installer/steps/if_step.py`, строка 17

Регэксп `r"^\s*(\!?)\s*([\w\.]+)\s*..."` — `[\w\.]+` (плюс) **требует хотя бы одного символа**, OK. Но `\!?` — ноль или один знак "!". Тогда строка `"!"` сама по себе не сматчится (нет имени после), и метод тихо выдаст False с warning. Это норм, но если кто-то напишет `"options.foo == "` (без значения), регэксп тоже не сматчит. И logger напишет warning, который скорее всего никто не увидит. Минор.

Серьёзнее — нет `&&`, `||`, `!=`. Если какой-то плагин в JSON захочет `"options.x && options.y"` — не сработает. Это by design (документировано как минимальный язык), но может привести к багам в будущих манифестах.

### 12. `_atomic_write_json` гонка с другим инстансом приложения

**Файл:** `main_window.py`, строки 892–907

Атомарная запись через `.tmp + os.replace` хороша, но:
1. Если файл `.tmp` уже занят процессом (другой инстанс), `open(tmp, "w")` упадёт — ловится в `finally`, который пытается удалить уже открытый. На Windows `os.remove` упадёт `PermissionError` для открытого файла, но в `finally` есть except OSError → проглотится.
2. Если приложение запущено дважды, оба пишут в один и тот же `app_config.json` независимо, без флока. Последний выигрывает. Не критично для конфига, но раздражает.

**Фикс:** использовать `NamedTemporaryFile` с уникальным суффиксом, чтобы не было коллизий с другим инстансом. Минимум — `mkstemp` в той же директории.

### 13. `MamboClickFilter` создаёт `Sound` на каждый клик мыши

**Файл:** `advanced_frame.py`, строки 86–97

```python
sound = pygame.mixer.Sound(wav_path)  # каждый раз заново читает WAV с диска
sound.play()
```

WAV-файл `mambo.wav` парсится при каждом нажатии. Объект `sound` — локальная переменная, после `play()` уходит в gc. Если play асинхронный и звук длиннее, чем срок жизни переменной, может быть прерывание. Плюс — **вкладка установлена в QtApp как глобальный фильтр кликов** (через `installEventFilter(self.mambo_filter)`, строка 1099), значит при включенном «mambo mode» каждый клик → reload+play.

**Фикс:** загрузить `Sound` один раз в `MamboClickFilter.__init__`, кэшировать.

### 14. `_has_relevant_files` — полный `os.walk` ради единственной проверки

**Файл:** `plugin_checker.py`, строки 137–148

```python
def _has_relevant_files(self, directory: str) -> bool:
    for _root, _dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith((...)):
                return True
```

Окей, в среднем проблем нет. Но если каталог огромный (сотни тысяч файлов), а первый релевантный файл — глубоко, ход медленный. На SSD норм. На HDD это может занять секунды.

**Фикс:** ограничить глубину рекурсии (см. `_fast_search` уже использует `max_depth=4`, можно использовать тот же `_fast_search` для проверки).

### 15. `signals.installed_check_done.emit(results)` с устаревшим epoch — частичная защита

**Файл:** `install_tab.py`, строки 559, 570

Если в середине цикла поменялась версия AE, поток вернётся **до** emit. Это ОК. Но в ветке `if epoch != self._installed_check_epoch: return` (строка 559) — если эпоха изменилась прямо перед строкой 565 (`is_installed(name, full_ver)`), вызов всё равно произойдёт. Не страшно, но трата времени.

Серьёзнее: если поток №1 застрял в `is_plugin_installed` (например, на медленном `os.walk`), а пользователь успел переключить версию 5 раз — каждое переключение запускает новый поток. Их накопится много, GIL не страдает (они в IO), но они конкурируют за DetectionCache, ProgramFiles и т.д.

**Фикс:** использовать `QtConcurrent.run` или `QThreadPool`, который автоматически отменяет старые задачи. Минимум — добавить cancellation token, который проверяется на каждом плагине.

### 16. `time.sleep(4)` в установке Mocha_Pro / RedGiant и группе Universe-Trapcode-MBS

**Файлы:** `installer_logic.py`, строки 388, 554, 626

```python
time.sleep(4)  # Mocha_Pro
time.sleep(6)  # RedGiant
time.sleep(4)  # Universe/Trapcode/MBS
```

«Подождать пока запустится Maxon App» — магические числа без обоснования. На медленных машинах 4 сек может не хватить, и `taskkill` выстрелит впустую (да, он `ignore_errors`, но процесс продолжит запуск). На быстрых — пользователь зря ждёт.

**Фикс:** делать `taskkill` в цикле с retry'ями, проверяя tasklist. Либо использовать WMI/psutil для дождаться появления процесса, потом убить.

### 17. `winreg.SetValueEx` и `winreg.CreateKeyEx` в цикле без явной обработки PermissionError

**Файл:** `installer_logic.py`, строки 362–372 (Flow), 500–510 (Uwu2x), `engine.py` `EnableCepDebugStep`

```python
for csxs in (...):
    try:
        with winreg.CreateKeyEx(...):
            winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
    except OSError as exc:
        print(f"Error modifying HKLM registry for CEP: {exc}")
```

`OSError` ловится, но `PermissionError` — это подкласс OSError, тоже ловится. Хорошо. **Но `print` — лог уходит в stdout, пользователь не увидит**. В новом ядре `EnableCepDebugStep` ловит `OSError` и использует `context.log` — норм.

Тот же код **дублируется в legacy `execute_native_install`** для Flow и Uwu2x. Когда плагины переедут на манифесты — старый код можно будет удалить.

### 18. В `_parse_plugins_data` дублируется код с `reload_custom_plugins`

**Файл:** `main_window.py`, строки 968–1000 vs 1053–1084

Скопированы 30+ строк парсинга custom-плагинов. Если поменять формат — править в двух местах. Уже сейчас они разошлись: в `reload_custom_plugins` нет специального кейса для RedGiant (но он там и не нужен).

**Фикс:** вынести в helper `_load_custom_plugins_from_dir(dir)`. См. патч.

### 19. `gdrive_id` без валидации может уронить gdown

**Файл:** `installer_logic.py`, `download_from_gdrive`

Если в `plugins.json` пришёл невалидный `gdrive_id` (например, `"PLACEHOLDER_UNIVERSE_GDRIVE_ID"` из `OLD_RG_MODE_PLUGINS`), `gdown.download(id="PLACEHOLDER_UNIVERSE_GDRIVE_ID", ...)` сделает запрос на несуществующий файл. Внутри `gdown` это может вылиться в HTTP 404, который ловится в `except Exception`, OK. Но шумит в логах.

**Фикс:** заранее валидировать формат gdrive_id (regex `[a-zA-Z0-9_-]+` длиной >= 25), сразу возвращать False с понятным сообщением.

---

## 🟢 ОПТИМИЗАЦИИ И КАЧЕСТВО КОДА

### 20. `clear_app_cache` делает два прохода по файлам

**Файл:** `advanced_frame.py`, строки 1353–1372

```python
for dp, _, fnames in os.walk(item_path):
    for fn in fnames:
        deleted_size += os.path.getsize(...)  # проход 1
shutil.rmtree(item_path, ignore_errors=True)  # проход 2 (тот же лес)
```

На больших каталогах (например, после установки 5-6 крупных плагинов) — это ощутимо. Можно использовать `os.scandir` рекурсивно с накоплением размера через `entry.stat().st_size`, либо просто не показывать точный размер (показать «Кэш очищен»).

**Фикс:** в патче — single-pass через `os.scandir`.

### 21. `unused import` в `core/installer/steps/registry.py`

**Файл:** `core/installer/steps/registry.py`, строка 6

```python
import ctypes
```

Не используется. Минор, но ruff/flake8 будут ругаться.

### 22. `_safe_name` в `manifest.py` не идемпотентен

**Файл:** `core/installer/manifest.py`, строка 165

```python
def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
```

Если `plugin_name` содержит ` ` (пробел) и `_` рядом, после прохода они становятся неразличимы. В принципе для имён плагинов из БД это не проблема, но если когда-то появятся плагины с одинаковыми после санитизации именами (`"Foo Bar"` и `"Foo_Bar"`), они получат один и тот же манифест-файл и перезапишут друг друга.

**Фикс:** добавлять короткий хэш для гарантированной уникальности. Низкий приоритет.

### 23. `_AE_VERSION_RE.sub` вызывается дважды в `_perform_installation`

**Файл:** `installer_logic.py`, строки 654–659 + контекст уже делает это сам (`InstallContext.expand` через `build_default_paths`)

```python
if custom_install_path and ae_version != "None":
    custom_install_path = re.sub(
        r"(?i)(After Effects\s*)20\d{2}",
        rf"\g<1>{ae_version}",
        custom_install_path,
    )
```

И внутри `pipeline.make_context → build_default_paths` — снова та же подмена. Дважды не критично (idempotent), но лишняя работа. Лучше делать один раз — на уровне pipeline.

### 24. `set(default_kws + json_kws)` теряет порядок

**Файл:** `main_window.py`, строки 964, 996

```python
self.plugin_keywords[name] = list(set(default_kws + json_kws))
```

Порядок ключевых слов влияет на скорость поиска: если самый «специфичный» keyword первым — `_fast_search` найдёт быстрее. После `set(...)` порядок недетерминирован → разные запуски будут давать разную скорость.

**Фикс:** дедупликация с сохранением порядка через `dict.fromkeys`.

### 25. В `pipeline.is_plugin_installed` тройная проверка манифеста

**Файл:** `core/installer/pipeline.py`, строки 289–300

Сначала читаем манифест с диска (IO), затем проверяем артефакты (новый IO в `artifacts_present`), затем при `False` — сносим манифест, затем проверяем `detect`, затем `legacy_check`. Если в системе ничего не установлено, мы каждый раз для **каждого плагина** делаем все три проверки. На UI старте `check_installed_plugins` дёргает is_plugin_installed для всех плагинов из БД (~30) — это 30+ файловых проверок.

Кэш есть (DetectionCache, TTL=60), но он **не помогает на первом старте**. Вариант: bulk-проверка через сканирование `installed/` один раз и матчинг по имени.

### 26. `apply_dark_titlebar` вызывается из QTimer.singleShot, не учитывает множественные открытия

**Файл:** `main_window.py`, многократно

Каждый показ окна вызывает `singleShot(0/10, lambda: apply_dark_titlebar(...))`. Если окно показывается часто — будет много мелких таймеров. Не критично.

### 27. `current_state.png` (28 КБ) и `thinker.png` (72 КБ) — лежат в репе и непонятно используются

Скриншоты для отладки? Если не используется — стоит удалить, в build не должны попадать.

### 28. Глобальный `_GDOWN_STDERR_LOCK` — узкое место для параллельных загрузок

Уже отметили в #4. По сути это превращает «параллельную» загрузку в последовательную из-за ограничения gdown'а. Если переписать на `requests`/`urllib3` с дисплеем прогресса — можно реально качать параллельно.

---

## ✅ ЧТО СДЕЛАНО ХОРОШО

- **Защита от Zip Slip** в `extract_zip.py` (строки 53–65) — образцово.
- **Транзакционная установка** с rollback — правильная архитектура.
- **`_safe_name`** для имени файла манифеста.
- **Атомарная запись JSON** через `.tmp + os.replace`.
- **Whitelist путей** для legacy uninstall.
- **DetectionCache** с TTL и инвалидацией.
- **`epoch`-механизм** в `check_installed_plugins` — корректно отменяет устаревшие async-проверки.
- **Корректное использование Qt-сигналов** для cross-thread UI.
- **Полное разделение ядра** (`core/installer`) от UI и legacy logic.
- **HiDPI-готовность** в `main.py`.
- **UAC-эскалация** правильно реализована.
- **i18n-хуки** на все строки UI.

---

## Список патчей (см. `fixed/`)

| Файл | Что исправлено |
|---|---|
| `core/installer/manifest.py` | #2, #22 |
| `core/installer/context.py` | #9 |
| `core/installer/steps/copy_dir.py` | #1 (вместе с transaction.py) |
| `core/installer/transaction.py` | #1 |
| `core/installer/steps/registry.py` | #21 |
| `core/installer/pipeline.py` | #25 (мелкие правки) |
| `installer_logic.py` | #3, #6, #7, #8, #19, #23 |
| `main_window.py` | #6, #18, #24 |
| `plugin_checker.py` | #14 |
| `advanced_frame.py` | #13, #20 |

Применить можно либо целиком, заменив файлы из `fixed/`, либо точечно — каждый из отчётов с `# AKSIOM-FIX` маркерами в комментариях.
