# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['swiss_backdrop.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['tplcodec', 'swiss_client', 'grab_screen', 'sdcard_export', 'zipfile', 'shutil', 'PIL.ImageTk', 'PIL._tkinter_finder', 'ftplib'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'matplotlib', 'pytest', 'scipy'],
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
    name='SwissBackdrop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_backdrop.txt',
    icon=['assets/swissbackdrop.ico'],
)
