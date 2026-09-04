# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
#
# PyInstaller build spec for the DGIWG GeoPackage Compliance Validator v1.63.
#
# Build with (from an Anaconda Prompt, "dgiwg" environment activated):
#     pyinstaller --clean --noconfirm DGIWG_Validator.spec
#
# (Normally you would run 02_build_exe.bat instead, which does this for you
#  and writes a log.)
#
# Produces a single console executable:
#     dist\DGIWG_Validator_v1_63.exe
#
# Console mode is intentional, not an oversight: the validator prints
# progress banners, asks Y/N questions on stdin when an optional library
# (shapely / Pillow / pyproj / lxml) is missing and --no-install was not
# passed, and prints the final verdict/summary line — a windowed
# (--noconsole) build would hide all of that. The interactive file-picker
# (tkinter) still works fine inside a console build.
#
# Optional libraries are bundled ONLY if they are installed in the
# environment this spec is built with. If one is missing, the exe still
# builds — it just falls back at runtime exactly the way the plain Python
# script does (that library's checks report PASS* instead of failing).

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = os.path.dirname(os.path.abspath(SPEC))

APP_NAME   = "DGIWG_Validator_v1_63"
ENTRY_FILE = os.path.join(HERE, "DGIWG_Validator_v1_63.py")
CACHE_FILE = os.path.join(HERE, "dgiwg_epsg_cache.json")

datas = []
if os.path.isfile(CACHE_FILE):
    # Destination "." = archive root, matching the path net.py looks for
    # (one directory above the dgiwg_validator package, i.e. the project
    # root / bundle root — see dgiwg_validator/net.py _EPSG_CACHE_CANDIDATES).
    datas.append((CACHE_FILE, "."))
else:
    print("  [spec] WARNING: dgiwg_epsg_cache.json not found next to the "
          "spec file — the exe will build without the offline EPSG cache.")

hiddenimports = [
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
]

OPTIONAL_LIBS = ("pyproj", "shapely", "PIL", "lxml")
for _pkg in OPTIONAL_LIBS:
    try:
        __import__(_pkg)
    except ImportError:
        print(f"  [spec] optional library '{_pkg}' is not installed in this "
              f"environment - it will NOT be bundled. The exe still builds "
              f"and runs; that library's checks fall back to PASS* at "
              f"runtime, same as running the .py script without it.")
        continue
    try:
        datas += collect_data_files(_pkg)
    except Exception as exc:
        print(f"  [spec] could not collect data files for '{_pkg}': {exc}")
    try:
        hiddenimports += collect_submodules(_pkg)
    except Exception as exc:
        print(f"  [spec] could not collect submodules for '{_pkg}': {exc}")

block_cipher = None

a = Analysis(
    [ENTRY_FILE],
    pathex=[HERE],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
