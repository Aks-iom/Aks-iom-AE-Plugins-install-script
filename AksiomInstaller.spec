# -*- mode: python ; coding: utf-8 -*-
"""
AksiomInstaller.spec
Сборка через PyInstaller.

[AKSIOM-FIX SPEC] Изменения относительно прошлой версии:
  1. Явно собираем плагины PyQt6.QtMultimedia (windowsmediaplugin.dll и
     audio-backend'ы) — без них QSoundEffect молча не играет.
     См. https://github.com/pyinstaller/pyinstaller/issues/7352
  2. Явные hiddenimports для winsound и QtMultimedia — на случай, если
     PyInstaller их пропустит при анализе.
  3. core/installer/* и его шаги добавлены в hiddenimports — модули грузятся
     лениво через importlib (например, build_steps), и static analyzer
     PyInstaller их не видит.
  4. Исключения для tkinter / unittest / xml.dom — экономит ~3-5 МБ в exe.
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

# -----------------------------------------------------------------------
# Базовые ресурсы приложения
# -----------------------------------------------------------------------
datas = [
    ('splash.png', '.'),
    ('logo.ico', '.'),
    ('mambo_assets', 'mambo_assets'),
]
binaries = []
hiddenimports = []

# -----------------------------------------------------------------------
# PyQt6 — все модули, плагины, переводы, qml.
# collect_all возвращает (datas, binaries, hiddenimports).
# -----------------------------------------------------------------------
tmp_ret = collect_all('PyQt6')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# -----------------------------------------------------------------------
# [AKSIOM-FIX SPEC #1] Явная подкладка multimedia-плагинов Qt.
# Без них QSoundEffect создаётся, но play() ничего не делает —
# windowsmediaplugin.dll отсутствует, аудио-backend'а нет.
# collect_all обычно их и так подтягивает, но дублируем явно — это безопасно
# (PyInstaller дедуплицирует) и гарантирует наличие плагинов в любых версиях.
# -----------------------------------------------------------------------
try:
    binaries += collect_dynamic_libs('PyQt6.QtMultimedia')
except Exception as exc:
    print(f'[spec] collect_dynamic_libs(QtMultimedia) failed: {exc}')

try:
    datas += collect_data_files('PyQt6.QtMultimedia')
except Exception as exc:
    print(f'[spec] collect_data_files(QtMultimedia) failed: {exc}')

# -----------------------------------------------------------------------
# [AKSIOM-FIX SPEC #2] Явные hidden-imports.
# winsound — Windows-builtin, обычно подхватывается, но без import его
# в момент analysis-фазы PyInstaller может не увидеть (мы импортируем его
# через try/except).
# QtMultimedia/QtMultimediaWidgets — наш fallback для звука.
# -----------------------------------------------------------------------
hiddenimports += [
    'winsound',
    'PyQt6.QtMultimedia',
    'PyQt6.sip',
]

# -----------------------------------------------------------------------
# [AKSIOM-FIX SPEC #3] Модули core/installer — грузятся через importlib
# (например, шаги в build_steps). Static analyzer не всегда их находит.
# -----------------------------------------------------------------------
hiddenimports += [
    'core',
    'core.installer',
    'core.installer.cache',
    'core.installer.context',
    'core.installer.custom_converter',
    'core.installer.detector',
    'core.installer.engine',
    'core.installer.manifest',
    'core.installer.pipeline',
    'core.installer.transaction',
    'core.installer.steps',
    'core.installer.steps.base',
    'core.installer.steps.copy_dir',
    'core.installer.steps.copy_file',
    'core.installer.steps.extract_zip',
    'core.installer.steps.if_step',
    'core.installer.steps.kill_process',
    'core.installer.steps.registry',
    'core.installer.steps.run_exe',
]

# -----------------------------------------------------------------------
# pygame — опциональный; если установлен, добавляем явно.
# Если pygame нет — try/except в advanced_frame.py обрабатывает это.
# -----------------------------------------------------------------------
try:
    pygame_data = collect_all('pygame')
    datas += pygame_data[0]
    binaries += pygame_data[1]
    hiddenimports += pygame_data[2]
except Exception as exc:
    print(f'[spec] collect_all(pygame) failed (skipping): {exc}')

# -----------------------------------------------------------------------
# gdown — для скачивания с Google Drive (используется в installer_logic.py).
# -----------------------------------------------------------------------
try:
    gdown_data = collect_all('gdown')
    datas += gdown_data[0]
    binaries += gdown_data[1]
    hiddenimports += gdown_data[2]
except Exception as exc:
    print(f'[spec] collect_all(gdown) failed (skipping): {exc}')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # [AKSIOM-FIX SPEC #4] Не тащим в exe то, что заведомо не используется.
    # Экономит несколько МБ и ускоряет старт.
    excludes=[
        'tkinter',
        'unittest',
        'pydoc',
        'doctest',
        'xml.dom',
        'xml.sax',
        'pdb',
        'idlelib',
        'lib2to3',
        'turtle',
        'turtledemo',
        # Test-suite Python'а
        'test',
        'tests',
        # Не используем эти Qt-модули — экономия ~10 МБ суммарно.
        # ВАЖНО: НЕ исключаем QtMultimedia (нужен для QSoundEffect) и
        # QtMultimediaWidgets (зависимость).
        'PyQt6.Qt3DCore',
        'PyQt6.Qt3DAnimation',
        'PyQt6.Qt3DExtras',
        'PyQt6.Qt3DInput',
        'PyQt6.Qt3DLogic',
        'PyQt6.Qt3DRender',
        'PyQt6.QtBluetooth',
        'PyQt6.QtCharts',
        'PyQt6.QtDataVisualization',
        'PyQt6.QtNfc',
        'PyQt6.QtPositioning',
        'PyQt6.QtQuick',
        'PyQt6.QtQuick3D',
        'PyQt6.QtQuickWidgets',
        'PyQt6.QtRemoteObjects',
        'PyQt6.QtSensors',
        'PyQt6.QtSerialPort',
        'PyQt6.QtSql',
        'PyQt6.QtTest',
        'PyQt6.QtWebChannel',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineQuick',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebSockets',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AksiomInstaller',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        # UPX иногда ломает Qt-плагины и vcredist DLL — лучше их не сжимать.
        'Qt6Core.dll',
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
        'Qt6Multimedia.dll',
        'Qt6Network.dll',
        'vcruntime140.dll',
        'vcruntime140_1.dll',
        'msvcp140.dll',
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['logo.ico'],
)
