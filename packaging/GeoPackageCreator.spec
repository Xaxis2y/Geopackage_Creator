# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for GeoPackage Creator (Windows).

Builds ONE of two layouts depending on the GPKG_ONEFILE environment variable:

    GPKG_ONEFILE=0  (default) -> one-dir build   -> dist\GeoPackageCreator\GeoPackageCreator.exe
    GPKG_ONEFILE=1            -> one-file build   -> dist\GeoPackageCreator.exe

Run via the build scripts (build_windows.ps1 / .bat) which set the flag and
the correct working directory, OR manually from the project ROOT:

    pyinstaller packaging\GeoPackageCreator.spec --noconfirm

IMPORTANT: build inside an environment where `from osgeo import gdal` works
(conda-forge gdal is strongly recommended). The collect_* helpers below pull
GDAL's DLLs and its gdal-data / proj-data folders into the bundle.
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# PyInstaller sets SPECPATH to the directory containing this spec file.
PKG_DIR = Path(SPECPATH).resolve()          # <root>\packaging
ROOT = PKG_DIR.parent                        # <root>

ONEFILE = os.environ.get("GPKG_ONEFILE", "0") == "1"
APP_NAME = "GeoPackageCreator"

# ---------------------------------------------------------------------------
# Data files bundled at the root of the application
# ---------------------------------------------------------------------------
datas = []

# ISO 19115 / GML schemas (used by core/metadata_handler.py via ../schemas)
schemas_dir = ROOT / "schemas"
if schemas_dir.is_dir():
    datas += [(str(p), "schemas") for p in schemas_dir.glob("*")]

# Bundled DGIWG validator package (kept as a folder so validation_gate.py and
# runtime_paths.py can auto-detect it; DGIWG_VALIDATOR_PATH points here).
validator_root = ROOT / "DGIWG_Validator_v1_55_updated"
if validator_root.is_dir():
    for p in validator_root.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            rel = p.parent.relative_to(ROOT)
            datas.append((str(p), str(rel)))

# GDAL + PROJ + pyproj data (gdal-data, proj.db, etc.)
for pkg in ("osgeo", "pyproj", "rasterio", "fiona"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Binaries (GDAL / GEOS / PROJ DLLs)
# ---------------------------------------------------------------------------
binaries = []
for pkg in ("osgeo", "shapely", "pyproj"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Hidden imports
# ---------------------------------------------------------------------------
hiddenimports = []
hiddenimports += collect_submodules("osgeo")
hiddenimports += collect_submodules("core")
hiddenimports += collect_submodules("dgiwg_validator")
hiddenimports += [
    "shapely",
    "shapely.geometry",
    "pyproj",
    "lxml",
    "lxml.etree",
    "lxml._elementpath",
    "sqlite3",
    "tkinter",
    "geopackage_creator",
    "geopackage_creator_gui",
    "runtime_paths",
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
# Make the project root AND the validator folder importable at build time.
pathex = [str(ROOT), str(validator_root)]

a = Analysis(
    [str(PKG_DIR / "app_main.py")],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "black", "pylint", "flake8", "sphinx"],
    noarchive=False,
)

pyz = PYZ(a.pure)

version_file = PKG_DIR / "version_info.txt"
icon_file = PKG_DIR / "app.ico"
icon_arg = str(icon_file) if icon_file.exists() else None

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        console=False,                 # GUI app: no console window by default
        disable_windowed_traceback=False,
        version=str(version_file) if version_file.exists() else None,
        icon=icon_arg,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        version=str(version_file) if version_file.exists() else None,
        icon=icon_arg,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name=APP_NAME,
    )
