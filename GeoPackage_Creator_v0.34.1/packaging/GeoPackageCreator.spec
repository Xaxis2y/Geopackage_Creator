# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
#
# GeoPackageCreator.spec
# ======================
# PyInstaller spec for GeoPackage Creator v0.34.1
#
# Controlled by environment variable:
#   GPKG_ONEFILE=1  -> single-file .exe  (dist\GeoPackageCreator.exe)
#   GPKG_ONEFILE=0  -> one-dir layout    (dist\GeoPackageCreator\GeoPackageCreator.exe)
#
# Build via:
#   packaging\build_windows.bat          (both layouts)
#   packaging\build_windows.bat -OneFileOnly
#   BUILD_EXE.bat                        (single-file only, legacy wrapper)

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# SPECPATH is set by PyInstaller to the directory containing this .spec file,
# i.e. <project_root>\packaging.  ROOT is one level up.
SPEC_DIR = Path(SPECPATH)          # noqa: F821  (PyInstaller built-in)
ROOT     = SPEC_DIR.parent

# ---------------------------------------------------------------------------
# One-file vs one-dir toggle
# ---------------------------------------------------------------------------
ONE_FILE = os.environ.get("GPKG_ONEFILE", "1") == "1"

# ---------------------------------------------------------------------------
# GDAL / PROJ / GEOS data & DLLs
# Collect everything osgeo ships: gdal-data, proj.db, DLLs, etc.
# ---------------------------------------------------------------------------
osgeo_datas       = collect_data_files("osgeo",         includes=["**/*"])
pyproj_datas      = collect_data_files("pyproj",         includes=["**/*"])
# GUI theming (v0.30.18). Pulls in ttkbootstrap's non-.py assets (app icons,
# localization files) the same defensive way osgeo/pyproj's data are pulled
# in above - collect_submodules below (hiddenimports) covers its .py code;
# this covers everything else so a theme/localization lookup can't fail at
# runtime for a file that quietly never made it into the bundle.
ttkbootstrap_datas = collect_data_files("ttkbootstrap", includes=["**/*"])

# On Windows conda builds the GDAL DLLs live next to python.exe or in
# Library\bin.  collect_dynamic_libs picks them up automatically.
osgeo_binaries  = collect_dynamic_libs("osgeo")

# ---------------------------------------------------------------------------
# Application data files
# ---------------------------------------------------------------------------
# DGIWG_GeoPackage_Validator_v1.62 (current bundled validator; v0.30.17 used
# DGIWG_Validator_v1_55_updated
# through v0.30.16; that folder no longer exists in the project tree, so the
# old tuple below would have made PyInstaller's Analysis() fail outright with
# a "source path does not exist" error the moment anyone tried to build this
# spec). This folder is intentionally NOT in hiddenimports: core/
# validation_gate.py's find_validator() and packaging/runtime_paths.py's
# bootstrap() both locate and load it at RUNTIME via sys.path.insert() +
# `from dgiwg_validator import checks` against a real on-disk directory next
# to the frozen exe (sys._MEIPASS for one-file, the app folder for one-dir) -
# a dynamic import PyInstaller's static analyzer cannot see and does not need
# to, since the files are plain .py source copied as data, not compiled into
# the PYZ. Bundling it here as data, at the SAME relative path the source
# tree already uses, is what lets runtime_paths.bootstrap()'s glob-based
# discovery (base / "DGIWG_GeoPackage_Validator_v1.62") find it unchanged
# inside a frozen build.
app_datas = [
    # Executed directly by the frozen executable's --schema-validation-worker
    # mode.  It must remain a real file, not only a module in the PYZ archive.
    (str(ROOT / "core" / "schema_validation_worker.py"),   "core"),
    # ISO / GML schemas used by metadata validation
    (str(ROOT / "schemas"),                             "schemas"),
    # Bundled DGIWG validator (needed by --validate / core/validation_gate.py)
    (str(ROOT / "DGIWG_GeoPackage_Validator_v1.62"),     "DGIWG_GeoPackage_Validator_v1.62"),
    # runtime_paths module must be importable from the bundle root
    (str(SPEC_DIR / "runtime_paths.py"),                 "."),
]

all_datas    = app_datas + osgeo_datas + pyproj_datas + ttkbootstrap_datas
all_binaries = osgeo_binaries

# ---------------------------------------------------------------------------
# Hidden imports
# PyInstaller's static analysis misses some dynamically-loaded modules.
# ---------------------------------------------------------------------------
hidden = [
    # GDAL / geospatial
    "osgeo",
    "osgeo.gdal",
    "osgeo.ogr",
    "osgeo.osr",
    "osgeo.gdal_array",
    "osgeo.gdalconst",
    *collect_submodules("osgeo"),
    # Geometry / projection
    "shapely",
    "shapely.geometry",
    *collect_submodules("shapely"),
    "pyproj",
    *collect_submodules("pyproj"),
    # XML
    "lxml",
    "lxml.etree",
    *collect_submodules("lxml"),
    # GUI
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
    "ttkbootstrap",
    *collect_submodules("ttkbootstrap"),
    # Standard library helpers often missed
    "logging.handlers",
    "xml.etree.ElementTree",
    "json",
    "pathlib",
    "threading",
    "subprocess",
    "tempfile",
    # Project packages
    "core",
    "core.config",
    "core.converter",
    "core.crs_converter",
    "core.dgiwg_compliance",
    "core.gdal_handler",
    "core.gdal_handler_concurrency",
    "core.metadata_handler",
    "core.raster_support",
    "core.report_generator",
    "core.validation_gate",
    "core.validators",
    # NOTE: the DGIWG validator package (dgiwg_validator, inside
    # DGIWG_GeoPackage_Validator_v1.62/) is deliberately NOT listed here.
    # It is loaded at runtime via sys.path.insert() against the bundled data
    # folder above (see the app_datas comment), which PyInstaller's static
    # import analysis cannot see and collect_submodules() cannot resolve
    # either (nothing named "dgiwg_validator" is importable from THIS
    # process at spec-build time - it only becomes importable once
    # find_validator()/bootstrap() add its folder to sys.path at app
    # runtime). Through v0.30.16 this list named the OLD folder,
    # "DGIWG_Validator_v1_55_updated", which was never actually an
    # importable top-level package even when that folder existed - v0.30.17
    # renamed the folder and this entry would have started hard-failing the
    # build (collect_submodules importing a name that does not exist raises)
    # instead of just being a harmless no-op. Removed rather than renamed.
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    # Entry point: no args -> GUI; with args -> CLI
    [str(SPEC_DIR / "app_main.py")],
    pathex=[
        str(ROOT),           # project root: core/, geopackage_creator*.py
        str(SPEC_DIR),       # packaging/: runtime_paths.py, app_main.py
    ],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Keep the bundle lean — test / dev tooling not needed at runtime
        "pytest",
        "setuptools",
        "pip",
        "IPython",
        "jupyter",
        "matplotlib",
        "numpy",      # remove if any dependency pulls it in transitively
        "pandas",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

# ---------------------------------------------------------------------------
# EXE / COLLECT
# ---------------------------------------------------------------------------
_version_file = str(SPEC_DIR / "version_info.txt")
_icon         = None   # set to str(ROOT / "packaging" / "icon.ico") if you add one

if ONE_FILE:
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="GeoPackageCreator",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=True,          # keep True so CLI mode shows output
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        version=_version_file,
        icon=_icon,
    )
else:
    # One-dir build (used by the Inno Setup installer)
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="GeoPackageCreator",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        version=_version_file,
        icon=_icon,
    )
    coll = COLLECT(  # noqa: F821
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="GeoPackageCreator",
    )
