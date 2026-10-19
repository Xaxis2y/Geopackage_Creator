@echo off
REM SPDX-License-Identifier: GPL-2.0-or-later
REM Copyright (c) 2026 Eui Soo SON
REM =============================================================================
REM  GeoPackage Creator v0.34.7 - Single-File EXE Builder
REM  Output: dist\GeoPackageCreator.exe
REM
REM  Requirements:
REM    - Conda installed (Miniconda or Anaconda)
REM    - GDAL available in conda env named "geopackage"
REM      (if env doesn't exist, this script creates it automatically)
REM
REM  Usage: double-click this file from the project root folder
REM =============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ================================================================
echo  GeoPackage Creator v0.34.7 - EXE Builder
echo ================================================================
echo.

REM ---- Check conda ----------------------------------------------------------
where conda >nul 2>&1
if errorlevel 1 (
    echo [ERROR] conda not found on PATH.
    echo.
    echo Install Miniconda from https://docs.conda.io/en/latest/miniconda.html
    echo Then re-run this script.
    pause
    exit /b 1
)

REM ---- Create or reuse conda env with GDAL 3.11.4 --------------------------
conda env list | findstr /C:"geopackage" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Creating conda env "geopackage" with GDAL...
    call conda create -y -n geopackage -c conda-forge python=3.11 gdal pyproj lxml
    if errorlevel 1 (
        echo [ERROR] Failed to create conda environment.
        pause
        exit /b 1
    )
) else (
    echo [INFO] Using existing conda env "geopackage"
)

REM ---- Verify GDAL ----------------------------------------------------------
echo [INFO] Verifying GDAL import...
call conda run --no-capture-output -n geopackage python -c "from osgeo import gdal; print('  GDAL', gdal.__version__, 'OK')"
if errorlevel 1 (
    echo [ERROR] GDAL import failed in conda env "geopackage".
    echo         Try: conda install -n geopackage -c conda-forge gdal
    pause
    exit /b 1
)

REM ---- Install PyInstaller + project deps -----------------------------------
echo [INFO] Installing PyInstaller and project dependencies...
call conda run --no-capture-output -n geopackage python -m pip install --upgrade pip --quiet
call conda run --no-capture-output -n geopackage python -m pip install "pyinstaller>=6.0" lxml --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

REM ---- Clean previous build output ------------------------------------------
echo [INFO] Cleaning previous build output...
if exist dist\GeoPackageCreator.exe del /f /q dist\GeoPackageCreator.exe
if exist build rmdir /s /q build

REM ---- Run PyInstaller ------------------------------------------------------
echo.
echo [BUILD] Building GeoPackageCreator.exe ...
echo         This may take 3-10 minutes. Please wait.
echo.
call conda run --no-capture-output -n geopackage python -m PyInstaller "%~dp0packaging\GeoPackageCreator.spec" --noconfirm --clean --distpath "%~dp0dist" --workpath "%~dp0build"
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed. Check output above for details.
    pause
    exit /b 1
)

REM ---- Result ---------------------------------------------------------------
if exist "dist\GeoPackageCreator.exe" (
    echo.
    echo ================================================================
    echo  BUILD SUCCESSFUL
    echo  Output: dist\GeoPackageCreator.exe
    for %%F in ("dist\GeoPackageCreator.exe") do (
        set /a SIZE_MB=%%~zF / 1048576
        echo  Size  : !SIZE_MB! MB
    )
    echo ================================================================
    echo.
    echo  Double-click the .exe to launch the GUI.
    echo  Or run from command line with arguments for CLI mode.
    echo.
) else (
    echo [ERROR] Build completed but output file not found.
)

pause
exit /b 0

