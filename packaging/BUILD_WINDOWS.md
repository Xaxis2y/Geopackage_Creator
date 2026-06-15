# Building GeoPackage Creator as a Windows App

This folder contains everything needed to turn GeoPackage Creator into a
distributable Windows application. You get **two** deliverables:

| Deliverable | What it is | Best for |
|-------------|-----------|----------|
| `dist\GeoPackageCreator.exe` | Single portable executable | Quick hand-off, copy-and-run, no install |
| `GeoPackageCreator-Setup-0.28.0.exe` | Classic `Setup.exe` installer | End users — installs to Program Files, adds Start Menu + Desktop shortcuts, includes an uninstaller |

Double-clicking the app with no arguments opens the **GUI**. The same `.exe`
also works as the **CLI** when you pass arguments (e.g.
`GeoPackageCreator.exe --source data.gdb --output out.gpkg --validate`).

> **You must build on Windows.** PyInstaller does not cross-compile, so the
> `.exe` cannot be produced on Linux/macOS. Build on the same Windows machine
> where the tool already runs.

---

## 1. Prerequisites

1. **Windows 10/11 (64-bit).**
2. **A Python environment where GDAL imports successfully.** Verify with:
   ```
   python -c "from osgeo import gdal; print(gdal.__version__)"
   ```
   If that fails, the most reliable fix is conda-forge GDAL (the build script
   sets this up for you):
   ```
   conda create -n gpkgbuild -c conda-forge python=3.11 gdal shapely pyproj lxml
   ```
3. **Inno Setup 6** (only for the `Setup.exe`): https://jrsoftware.org/isinfo.php

---

## 2. Build the executables

From the **project root** (the folder containing `geopackage_creator.py`):

```bat
packaging\build_windows.bat
```

That builds **both** the one-file and one-dir layouts. Useful variants:

```bat
packaging\build_windows.bat -OneFileOnly      :: just the single .exe
packaging\build_windows.bat -OneDirOnly       :: just the installer payload
packaging\build_windows.bat -UseCurrentEnv    :: skip conda, use active Python
```

Outputs land in:

```
dist\GeoPackageCreator.exe              <- single-file portable app
dist\GeoPackageCreator\GeoPackageCreator.exe   <- one-dir build (installer input)
```

What the script does, in order: picks/creates the GDAL-capable Python,
verifies `from osgeo import gdal`, installs PyInstaller, cleans old output,
and runs `pyinstaller packaging\GeoPackageCreator.spec` once per layout
(toggled by the `GPKG_ONEFILE` environment variable inside the spec).

---

## 3. Build the installer (optional)

After the **one-dir** build exists:

1. Open `packaging\installer\GeoPackageCreator.iss` in the Inno Setup
   Compiler and click **Compile** (or run
   `ISCC.exe packaging\installer\GeoPackageCreator.iss`).
2. The installer appears at
   `packaging\installer\Output\GeoPackageCreator-Setup-0.28.0.exe`.

The installer bundles the whole one-dir folder, creates Start Menu and
optional Desktop shortcuts, registers an uninstaller, and offers to launch the
app at the end.

---

## 4. How the bundling works (for maintainers)

- **`app_main.py`** is the single PyInstaller entry point. No args → GUI; with
  args → CLI. This keeps one `.exe` serving both roles.
- **`runtime_paths.py`** runs first and fixes resource locations for the
  frozen build: it points `GDAL_DATA` / `PROJ_LIB` at the bundled data,
  sets `DGIWG_VALIDATOR_PATH` so `core/validation_gate.py` finds the bundled
  validator, and adds the bundle root to `sys.path`.
- **`GeoPackageCreator.spec`** collects, into the bundle:
  - `core/` package and `geopackage_creator.py` / `geopackage_creator_gui.py`
  - `schemas/` (ISO 19115 / GML XSDs used by metadata validation)
  - `DGIWG_Validator_v1_55_updated/` (the `--validate` engine)
  - GDAL/GEOS/PROJ DLLs + `gdal-data` / `proj.db` via
    `collect_dynamic_libs` / `collect_data_files`
- **`version_info.txt`** stamps the `.exe` with version metadata.
- A small frozen-aware tweak in `geopackage_creator_gui.py`
  (`convert_in_console`) makes the GUI's "run in console" button call the
  frozen `.exe` instead of `python geopackage_creator.py`.

---

## 5. Smoke test the build

```bat
:: GUI
dist\GeoPackageCreator.exe

:: CLI + validation (same .exe)
dist\GeoPackageCreator.exe --source TEST01\canvec_250226_472009.gdb ^
    --output out.gpkg --title "Test" --org "Org" --nation CAN --validate
```

Confirm: the GUI opens; the CLI run produces `out.gpkg`; and `--validate`
writes a DGIWG report. If `from osgeo import gdal` worked at build time but the
frozen app reports missing `gdal-data`/`proj.db`, re-run the build inside the
conda env (it ships the data folders the GDAL wheels sometimes omit).

---

## 6. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: osgeo` at build | Build in the conda env; don't use a plain venv without GDAL. |
| App starts then exits; CRS/Req 13 errors | `gdal-data`/`proj.db` not bundled — rebuild via conda; `runtime_paths.py` will set `GDAL_DATA`/`PROJ_LIB`. |
| `--validate` says validator not found | Confirm `DGIWG_Validator_v1_55_updated\dgiwg_validator\checks.py` was bundled; `runtime_paths.py` sets `DGIWG_VALIDATOR_PATH`. |
| Antivirus flags the one-file exe | Common PyInstaller false positive; prefer the signed installer, or code-sign the exe. |
| Slow first launch (one-file) | Expected — it unpacks to a temp dir each run. Use the one-dir/installer build for speed. |
| Missing hidden import at runtime | Add the module name to `hiddenimports` in `GeoPackageCreator.spec`. |
