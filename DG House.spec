# -*- mode: python ; coding: utf-8 -*-
"""Build DG House — chay: pyinstaller "DG House.spec\""""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
root = Path(SPECPATH)

ctk_datas, ctk_binaries, ctk_hidden = collect_all("customtkinter")

datas = [
    (str(root / "template.xlsx"), "."),
    (str(root / "supabase"), "supabase"),
    (str(root / ".env.example"), "."),
] + ctk_datas

a = Analysis(
    ["app.py"],
    pathex=[str(root)],
    binaries=ctk_binaries,
    datas=datas,
    hiddenimports=[
        "psycopg",
        "psycopg_binary",
        "supabase",
        "httpx",
        "httpcore",
        "h2",
        "anyio",
        "pandas",
        "openpyxl",
        "dotenv",
    ]
    + ctk_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DG House",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DG House",
)
