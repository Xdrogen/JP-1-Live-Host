# jamjum.spec —— 无图标版
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
datas.append(('jamjum.ico', '.'))
for pkg in ('_sounddevice_data', '_soundfile_data'):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

hiddenimports = [
    'mido.backends.pygame',
    'pygame.midi',
    'sounddevice',
    'soundfile',
] + collect_submodules('scipy.signal')

a = Analysis(
    ['jamjum_jp1.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['silent_stdout.py'],
    excludes=['matplotlib',
              'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='jamjum_jp1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=r'E:\JAMJUM JP-1\jamjum.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='jamjum_jp1',
)