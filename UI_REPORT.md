# Отчёт по UI (вторая итерация)

Проверены: `styles.py`, `install_tab.py`, `advanced_frame.py`, `main_window.py`.
Категории — те же:
- 🔴 **Критично** — баг или утечка ресурсов
- 🟡 **Серьёзно** — заметно влияет на UX, но приложение не падает
- 🟢 **Косметика / тонкая настройка**

---

## 🔴 КРИТИЧНОЕ

### UI-1. `_safe_update_last_log_line_ui` — `cursor.SelectionType.LineUnderCursor` удаляет текст не целиком

**Файл:** `install_tab.py`, строки 627–633

```python
cursor.movePosition(cursor.MoveOperation.End)
cursor.select(cursor.SelectionType.LineUnderCursor)
cursor.removeSelectedText()
cursor.insertText(msg)
```

`LineUnderCursor` в `QTextEdit` выбирает **один визуальный line** документа,
но если последняя «логическая строка» у тебя кончается переводом строки и
курсор прыгнул на пустую следующую строку (а это происходит после
`log_textbox.append(...)` — Qt вставляет блок), `LineUnderCursor` выберет
пустую строку, `insertText(msg)` добавит msg **после** старой строки → лог
покажет двойной прогресс типа:

```
Загрузка X: 50%
Загрузка X: 75%
```

вместо одной обновляющейся строки. Происходит конкретно при чередовании
`log_added` и `last_log_updated` сигналов из gdown.

**Фикс:** перед `select(LineUnderCursor)` явно отступить курсор на одну
позицию или удалять последний `QTextBlock` через `cursor.movePosition(StartOfBlock, KeepAnchor); cursor.removeSelectedText()`.

### UI-2. `Sound` после `play()` уходит в gc — обрывистый звук в `MamboClickFilter` (уже исправлено в патче #13)

Зафиксировано в первой итерации, но добавляю сюда для полноты — в
`_on_mambo_changed` музыка `pygame.mixer.music.play(-1)` нормально хранится
самим pygame, но щелчки через старый `pygame.mixer.Sound(wav)` теряли
ссылку. Уже пофиксил в `advanced_frame.py`.

### UI-3. `_update_last_log_line` правит `persistent_log_history[-1]` через индекс

**Файл:** `install_tab.py`, строка 620

```python
if self.app.persistent_log_history:
    self.app.persistent_log_history[-1] = entry
```

После моего патча #6 `persistent_log_history` стал `collections.deque`.
**`deque` НЕ поддерживает присваивание по `[-1] = entry`** в старых версиях
Python — поддерживает с 3.5+. Но если `maxlen` достигнут, при новом
`append` слева всё равно сдвигается. То есть `[-1] = entry` работает,
но **ломает «обновление последней строки» сразу после переполнения**: если
последняя запись уехала на индекс -2 после нового append, мы перепишем
не ту строку.

**Фикс:** не трогать `persistent_log_history[-1]`. Полностью убрать эту
строку — `last_log_updated` всё равно поправит UI. История логов и так
обновляется через `log_history[-1] = entry`, а persistent — это **архив**,
ему достаточно знать факт сообщения.

### UI-4. `clear_logs` чистит только `log_history` и UI, но `_update_last_log_line` пишет в `persistent_log_history`

**Файл:** `install_tab.py`, строка 639–641

```python
def clear_logs(self) -> None:
    self.app.log_history.clear()
    self.log_textbox.clear()
```

После очистки `log_history` пуст. Если затем gdown шлёт прогресс-сигнал,
`_update_last_log_line` (строки 612–621) сделает:
```python
if self.app.log_history:        # False — НЕ обновит
    self.app.log_history[-1] = entry
if self.app.persistent_log_history:  # True — обновит «чужую» прошлую строку
    self.app.persistent_log_history[-1] = entry
```

То есть persistent-история будет испорчена прогресс-обновлением, не
относящимся к её последней записи. Связан с UI-3.

**Фикс:** в `clear_logs` чистить и `persistent_log_history` (уже сделано в
патче #6 main_window). Плюс убрать заигрывания с `[-1]` для persistent
(см. UI-3).

---

## 🟡 СЕРЬЁЗНОЕ

### UI-5. `version_seg.set_value(... emit=False)` после установки нового списка не вызывает `_on_version_changed`

**Файл:** `install_tab.py`, строки 187–189

При смене языка (а версии — числовые, языку всё равно) проблем нет. Но в
`AdvancedFrame.update_drive_widget` (строки 1173-1180) есть такой паттерн:

```python
if self.app.ae_drive in drives: 
    self.drive_seg.set_value(self.app.ae_drive, emit=False)
else:
    self.drive_seg.set_value(drives[0], emit=False)
    self.change_ae_drive(drives[0])  # вручную
```

Это OK. **Но `set_values` внутри сам вызывает `set_value(values[0], emit=False)`**
если предыдущее значение не входит в новый список (styles.py строка 430-431).
В update_drive_widget после `set_values` сразу вызывается `set_value(...)`
повторно — это второй вызов, но без эффекта (значение совпало). **Лишний
вызов, не баг.**

Реальная мелочь: в `set_values` (`styles.py` 430-433) при пересоздании,
если values пустой, `_current_value` остаётся старый — потом обращение
к `self._buttons[self._current_value]` будет KeyError. Случай вряд ли
возникнет, но защита нужна.

### UI-6. `force_install` чекбокс — `state == Qt.CheckState.Checked.value` сравнение через `.value`

**Файл:** `install_tab.py`, строка 289

```python
lambda state: setattr(self.app, "force_install", state == Qt.CheckState.Checked.value)
```

`stateChanged` отдаёт `int` в PyQt6. `Qt.CheckState.Checked.value == 2`,
`Qt.CheckState.Unchecked.value == 0`, `Qt.CheckState.PartiallyChecked.value == 1`.
Tristate здесь не используется, поэтому `state == 2` работает. **Но в
других местах кода используется `state != 0` или `cb.isChecked()`** —
непоследовательность стиля. Не баг, но если когда-то PyQt поменяет API
(было движение от int к enum в PyQt6.0–6.4), сломается именно этот вариант.

**Фикс:** заменить на `cb.isChecked()` напрямую через атрибут. Как
консистентность кода.

### UI-7. `_safe_log` дублирует `log_textbox.append(msg)` — добавляет переводы строк

**Файл:** `install_tab.py`, строки 604–610

```python
self.log_textbox.append(msg)
adv = getattr(self.app, "advanced_frame_widget", None)
if adv is not None and hasattr(adv, "append_log"):
    adv.append_log(msg + "\n")
```

`QTextEdit.append` сам добавляет блок (≈ перевод строки). А в
`AdvancedFrame.append_log` (строки 246–250) используется
`insertPlainText(text)` без блокового добавления, и нам передают
`msg + "\n"`. Это корректно. **Но при многострочном msg** (например,
`"\n----------------------------------------\n📦 ПЛАГИН: ..."`)
поведение `append` и `insertPlainText` слегка разное:
- В install_tab лог: `\n` в начале даст пустую строку перед заголовком.
- В advanced лог: `\n` в начале и в конце дадут две пустые строки.

Не баг, но **косметически логи в двух окнах выглядят по-разному**. Также
длинный персистентный лог в advanced постепенно расходится по форматированию
с install-tab лог.

**Фикс:** оба лога должны использовать одинаковый код вставки, лучше
завернуть в `append(text)` для обоих.

### UI-8. `_apply_installed_marks` пересоздаёт QSS целиком при каждой смене статуса

**Файл:** `install_tab.py`, строки 574–587

```python
template = getattr(cb, "_base_qss_template", None)
color = "#4CAF50" if installed else COLOR_TEXT
if template:
    cb.setStyleSheet(template.format(color=color))
```

При каждой проверке всех плагинов (~30 чекбоксов) — `setStyleSheet`
триггерит **полный re-style и repaint** для каждого. На первом старте,
когда `check_installed_plugins` стреляет ещё до отрисовки — окей. Но при
переключении версии AE (`_on_version_changed`) — это 30 принудительных
QSS-апдейтов в одном кадре. Заметно мерцает.

**Фикс:** менять только `setProperty("installed", True/False)` + добавить
правило `QCheckBox[installed="true"] { color: #4CAF50; }` в глобальный QSS.
Тогда смена статуса = `cb.style().polish(cb)` (быстрее, не пересоздаёт
indicator).

Это серьёзная переработка — оставлю как улучшение во второй итерации;
сейчас текущее работает.

### UI-9. `cursor.MoveOperation.End` в `_safe_update_last_log_line_ui` не блокирует автоскролл

**Файл:** `install_tab.py`, строка 632–633

```python
self.log_textbox.setTextCursor(cursor)
self.log_textbox.ensureCursorVisible()
```

Если пользователь во время прогресса загрузки вручную проскроллил наверх
(посмотреть что было в начале), `ensureCursorVisible` дёрнет скролл вниз
при каждом обновлении прогресса (5/10 раз в секунду). Раздражает.

**Фикс:** проверять перед скроллом — стоит ли скроллбар внизу:
```python
bar = self.log_textbox.verticalScrollBar()
auto_follow = bar.value() >= bar.maximum() - 10
...
if auto_follow:
    self.log_textbox.ensureCursorVisible()
```

### UI-10. `SmoothScrollArea.wheelEvent` ловит даже горизонтальные `delta.x()`

**Файл:** `install_tab.py`, строки 80–99

```python
delta = event.angleDelta().y()
if delta == 0:
    event.ignore()
    return
```

На MacBook trackpad / горизонтальной мыши `angleDelta().y()` будет 0,
событие игнорируется. Окей. **Но на трэкпадах с `pixelDelta()`** (continuous
scroll — Magic Mouse, current-gen Surface) `angleDelta()` возвращает
маленькие дискретные значения 1–8, а не привычные ±120. Тогда:
```python
step = max(20, int((bar.maximum() - bar.minimum()) * 0.06))
```
шаг 6% от диапазона = огромный для маленьких пиксельных дельт. На
тачскреене один пиксель → прыжок на 6% диапазона.

**Фикс:** учитывать `pixelDelta()`:
```python
pixel_delta = event.pixelDelta()
if not pixel_delta.isNull():
    bar.setValue(bar.value() - pixel_delta.y())
    event.accept()
    return
```

Если приложение ориентировано на Windows-десктоп — низкий приоритет.

### UI-11. `set_values` в `SegmentedButton` тихо ломается, если values пустой

**Файл:** `styles.py`, строки 400–433

```python
def set_values(self, values: list[str]) -> None:
    for btn in self._buttons.values(): ...
    self._buttons.clear()
    for value in values: ...
    if values and self._current_value not in values:
        self.set_value(values[0], emit=False)
    elif self._current_value in values:
        self._buttons[self._current_value].setChecked(True)
```

Если `values == []`, `_current_value` остаётся, кнопок нет → следующий
`set_value(prev_value)` упадёт `KeyError`. На практике вряд ли вызовут
с пустым списком, но безопасный сценарий — обнулить `_current_value`.

**Фикс:**
```python
if not values:
    self._current_value = None
    return
```

### UI-12. `apply_old_rg_visibility` сбрасывает чекбоксы — а пользователь, возможно, специально включил Universe и потом передумал, потерял состояние

**Файл:** `install_tab.py`, строки 442–443

Когда old_rg_mode выключают, чекбоксы Universe/Trapcode/MBS снимаются.
Это правильно для безопасности (нельзя установить «скрытый» плагин), но
пользователь может потом снова включить old_rg_mode и обнаружить, что его
выбор пропал. **Не баг — поведение by design**, но стоит залогировать в
лог-окне типа «Отключён old_rg_mode — Universe/Trapcode/MBS сняты с выбора».

### UI-13. Кнопки в опциях имеют разный стиль

**Файл:** `advanced_frame.py`, строки 977–1004

`btn_maxon_activation` и `btn_save_settings` имеют **inline-стили**, а
большинство кнопок выше используют либо global QSS, либо objectName
(`DarkButton`, `InstallButton`). Inline-стили:
1. Перебивают глобальную тему — при изменении палитры эти две кнопки
   останутся прежними.
2. Используется `padding: 6px 18px` для save и `6px 14px` для maxon —
   разные. Кнопки рядом будут разной высоты.
3. `:pressed { background-color: #2a5a8a }` для save — это **синий!**
   Не из палитры — палитра у нас фиолетовая (COLOR_ACCENT = `#7560d6`).
   При нажатии на save кнопка прыгнет в синий — баг копипасты.

**Фикс:** убрать inline-стили, дать им objectName. Уже есть `DarkButton`
для maxon, `InstallButton` для save можно использовать.

### UI-14. `un_btn` (кнопка Delete в Uninstall) тоже inline-стиль с захардкоженными цветами

**Файл:** `advanced_frame.py`, строка 911

Та же проблема — захардкоженный `#882222 / #aa3333`. Палитру не
поддерживает. Лучше objectName="DangerButton" и в QSS.

### UI-15. В правой панели install_tab лог-кнопки «Очистить логи» нет

**Файл:** `install_tab.py`, общая структура

Есть `clear_logs()` метод, но **его никто не вызывает из UI**. В оригинале
видимо была кнопка, в нынешнем UI её нет. Метод вызывается только из
`run_install_process` через `widget.clear_logs()`. Пользователь не может
почистить лог из главного окна — только закрыть и переоткрыть установщик.

**Фикс:** добавить `QPushButton("Очистить логи")` рядом с кнопкой языка
в `right_top`. Или хотя бы пункт в меню/контекстное.

### UI-16. `request_uninstall` блокирует UI при удалении

**Файл:** `advanced_frame.py`, строки 921–927

```python
self.app.uninstall_plugin(plugin_name, full_ver)
QTimer.singleShot(200, self.build_uninstall_ui)
```

`uninstall_plugin` синхронный и может занять секунды (rmtree большой
папки + winreg операции). UI замораживается. На быстрых SSD незаметно,
на сетевых дисках или сильно фрагментированных — тормоза.

**Фикс:** запускать в `threading.Thread`, по окончании emit'ить сигнал
для перезаливки списка.

---

## 🟢 КОСМЕТИКА И МЕЛОЧИ

### UI-17. `selected_types = list(data.get("c_types", ["zip"]))` — порядок типов не сохраняется

**Файл:** `advanced_frame.py`, строка 349

При редактировании плагина с `c_types: ["file", "zip"]` (вдруг такое
бывает) UI сначала покажет в неправильном порядке: цикл идёт `for t_id
in ("zip", "exe", "file", "reg"):` — карточки рендерятся в этом порядке,
а не в порядке `selected_types`. Минор.

### UI-18. `_dim_label` создаёт новый `QLabel` каждый раз, в т.ч. в циклах

**Файл:** `advanced_frame.py`, строка 1421–1424

Метод вызывается из `load_plugin_to_form` при каждом переключении плагина
~10 раз. На каждый — новый QLabel и новый setStyleSheet. Не drama, но
если хотим супер-чистоту — кэшировать стиль через objectName="DimLabel"
(он уже есть в global QSS, строки 115–117!).

**Фикс:** заменить `_dim_label` на `QLabel(text); setObjectName("DimLabel")`
напрямую.

### UI-19. `t.get("c_warn_ph", "Текст предупреждения")` — русский fallback

**Файл:** `advanced_frame.py`, многократно (строки 287, 352, 419, 424, 605, 1080, 1413)

Hardcoded русский текст в качестве fallback. Если key пропадёт из
lang.json и язык установлен en — английский пользователь увидит русский
текст. Должны быть английские fallback'и.

### UI-20. `print(f"...")` вместо `self.app.log(...)` в advanced_frame

**Файл:** `advanced_frame.py`, строки 271, 583, 589, 625, 1248

`print` уходит в stdout, который пользователь не видит. Если нужно сообщить
о проблеме — через `self.app.log(...)`. Если просто отладка — стоит
использовать модуль `logging` с уровнем DEBUG, чтобы релизная сборка
не засирала консоль.

### UI-21. SplashDialog — `setFixedSize(pixmap.size())`

**Файл:** `main_window.py`, строки 192–193

Если splash.png в репозитории — фиксированного размера. **На HiDPI экранах
(125%, 150%, 200% scaling)** Qt без `Qt.AA_EnableHighDpiScaling` (а в Qt6
он default-on) увеличит окно, но pixmap останется маленьким. Картинка
будет смазанная по углам. Можно прогружать `splash@2x.png` через `setDevicePixelRatio`,
либо использовать SVG. Минор.

### UI-22. `self.update_btn_container` без минимальной ширины

**Файл:** `install_tab.py`, строки 318–322

Контейнер для кнопки Update изначально пустой. Когда кнопка появляется
(`show_update_button`), она его раздувает. На узком окне (820px минимум)
это резко сжимает заголовок «Event Log» и кнопку языка. Нет резерва
места.

**Фикс:** ограничить максимальную ширину `update_btn_container.setMaximumWidth(280)`,
чтобы текст кнопки сокращался эллипсисом.

### UI-23. `padding: 4px 12px` против `padding: 8px 14px` — кнопки разной высоты

**Файл:** `advanced_frame.py`, строки 911 (un_btn), `styles.py` (`QPushButton`, строка 125)

`QPushButton#un_btn` имеет padding 4px 12px, обычный QPushButton — 8px 14px.
Кнопки Delete в списке uninstall на ~8 пикселей короче по высоте, чем
кнопки Browse рядом. Глаз цепляется.

### UI-24. `setStyleSheet("background-color: #2a2a2a; ...")` для row в build_sync_ui

**Файл:** `advanced_frame.py`, строка 777

`#2a2a2a` — не палитровый. В палитре `COLOR_CARD_ALT = #2a2a35` и
`COLOR_BG = #1c1c22`. Это чужой оттенок. Видимо, копипаста.

### UI-25. `populate_logs` в advanced — `for entry in self.app.persistent_log_history: self.adv_log_textbox.append(...)`

**Файл:** `advanced_frame.py`, строки 240–244

При 10 000 записей persistent (после моего fix #6) — 10 000 `append`
вызовов = 10 000 layout-перерасчётов QTextEdit. Зависание на 1-3 секунды
при открытии вкладки Logs.

**Фикс:** собрать всё в одну строку и сделать один `setPlainText(joined)`.

### UI-26. Иконка ⌕ может не отрисоваться без Segoe UI Symbol

**Файл:** `install_tab.py`, строка 220

```python
self.lbl_search_icon = QLabel("⌕", plugins_header)
```

Юникодный glyph U+2315 «WATCH». Не на всех Windows-системах (старые
билды Windows 7) есть Segoe UI Symbol с этим символом. Появится квадратик.

**Фикс:** использовать иконку из QStyle, например `QStyle.StandardPixmap.SP_FileDialogContentsView`,
или встроить SVG/PNG лупы, как уже сделано с галочкой.

### UI-27. `version_separator.setStyleSheet(... "max-height: 1px;")`

**Файл:** `install_tab.py`, строки 200–205

Установка `setFixedHeight(1)` плюс `max-height: 1px` в QSS — дублирование.
QSS перебьёт setFixedHeight (Qt6 особенность). Не баг, но избыточно.

### UI-28. В `apply_old_rg_visibility` нет проверки на `None` для `cb`

**Файл:** `install_tab.py`, строка 442

```python
if not old_rg_on and cb is not None and cb.isChecked():
    cb.setChecked(False)
```

`cb` может быть удалён вместе с row. Защита уже есть (`is not None`),
но **`cb.isChecked` может стрельнуть на удалённом C++-объекте**, если
`row.deleteLater()` уже отработал, но ссылка осталась в `checkbox_widgets`.
В текущем коде `apply_old_rg_visibility` не вызывается во время удаления,
но ловушка есть. Минор.

---

## ✅ Что в UI сделано хорошо

- **deque вместо list** для persistent_log_history (после моего fix #6).
- Сигнальная архитектура — потокобезопасная, главный поток не дёргается напрямую.
- **`epoch`-механизм** в `check_installed_plugins`.
- HiDPI-ready (Qt6 default scaling).
- `apply_dark_titlebar` для Windows DWM.
- **CHECKMARK_PATH через tempfile** — обходит баг QSS-data:URL в Qt6.
- **`SmoothScrollArea`** с покадровой анимацией (хороший touch).
- Карточки с `objectName="Card"` — стилизуются через QSS централизованно.
- **First-run dialog** для пути AE — UX+1.
- Все сигналы корректно `disconnect`'ятся при пересоздании в `update_label`.
- SegmentedButton — корректно реализованный exclusive-toggle с custom QSS.
