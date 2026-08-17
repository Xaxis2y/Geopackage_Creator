@echo off
REM SPDX-License-Identifier: GPL-2.0-or-later
REM Copyright (c) 2026 Eui Soo SON
setlocal enabledelayedexpansion
chcp 65001 >nul
title GeoPackage Creator - Anaconda Start

REM ============================================================================
REM  Anaconda_Start.bat  -  GeoPackage Creator v0.30.19
REM
REM  One-click launcher that:
REM    1. Locates your Anaconda / Miniconda installation
REM    2. Creates the "geopackage" conda environment if it does not exist yet
REM       (GDAL + lxml + pyproj + reportlab + pytest, from conda-forge)
REM    3. Activates that environment
REM    4. Opens a ready-to-use prompt in this project folder
REM
REM  Just double-click this file, or run it from any Command Prompt.
REM  You should NO LONGER work in the (base) environment for this tool.
REM ============================================================================

set "ENV_NAME=geopackage"
set "PROJECT_DIR=%~dp0"

echo ============================================================
echo   GeoPackage Creator - Anaconda Start
echo ============================================================
echo.

REM ---- 1. Locate conda -------------------------------------------------------
set "CONDA_BAT="
for %%P in (
    "%USERPROFILE%\anaconda3"
    "%USERPROFILE%\miniconda3"
    "%USERPROFILE%\Anaconda3"
    "%USERPROFILE%\Miniconda3"
    "C:\ProgramData\anaconda3"
    "C:\ProgramData\miniconda3"
    "%PROGRAMDATA%\Anaconda3"
    "%LOCALAPPDATA%\Continuum\anaconda3"
) do (
    if exist "%%~P\Scripts\activate.bat" (
        set "CONDA_BAT=%%~P\Scripts\activate.bat"
        goto :found_conda
    )
)

REM Fall back to a conda already on PATH (e.g. launched from Anaconda Prompt).
where conda >nul 2>nul
if %errorlevel%==0 (
    for /f "delims=" %%C in ('where conda') do (
        for %%D in ("%%C") do set "CONDA_BAT=%%~dpDactivate.bat"
        goto :found_conda
    )
)

echo [ERROR] Could not find Anaconda/Miniconda automatically.
echo         Open "Anaconda Prompt" and run this script from there, or edit the
echo         search paths near the top of this file to point at your install.
echo.
pause
exit /b 1

:found_conda
echo [ok] Using conda activation script:
echo      !CONDA_BAT!
echo.

REM ---- 2. Initialize conda for this shell (activates base) -------------------
call "!CONDA_BAT!"
if errorlevel 1 (
    echo [ERROR] Failed to initialize conda.
    pause
    exit /b 1
)

REM ---- 3. Create the environment if it is missing ---------------------------
call conda env list | findstr /B /C:"%ENV_NAME% " >nul
if errorlevel 1 (
    echo [..] The "%ENV_NAME%" environment does not exist yet - creating it now.
    echo      This downloads GDAL and its dependencies from conda-forge and can
    echo      take several minutes the first time. Please wait...
    echo.
    if exist "%PROJECT_DIR%environment.yml" (
        call conda env create -n %ENV_NAME% -f "%PROJECT_DIR%environment.yml"
    ) else (
        call conda create -y -n %ENV_NAME% -c conda-forge python=3.11 gdal lxml pyproj reportlab pytest
    )
    if errorlevel 1 (
        echo.
        echo [ERROR] Environment creation failed. See the messages above.
        pause
        exit /b 1
    )
    echo.
    echo [ok] Environment "%ENV_NAME%" created.
) else (
    echo [ok] Environment "%ENV_NAME%" already exists.
)
echo.

REM ---- 4. Activate the environment ------------------------------------------
call conda activate %ENV_NAME%
if errorlevel 1 (
    echo [ERROR] Could not activate "%ENV_NAME%".
    pause
    exit /b 1
)

REM ---- 5. Move to the project folder and print a quick GDAL check ------------
cd /d "%PROJECT_DIR%"
echo ============================================================
echo   Ready.  Active environment: %ENV_NAME%
python -c "import sys;print('   Python',sys.version.split()[0])" 2>nul
python -c "from osgeo import gdal;print('   GDAL  ',gdal.__version__)" 2>nul || echo   [WARN] GDAL not importable - the environment may need rebuilding.
echo   Folder: %CD%
echo ------------------------------------------------------------
echo   Common commands:
echo     python dev_tools\run_release_check_v0.30.18.py    ^(run the full release checks^)
echo     python geopackage_creator_gui.py            ^(launch the GUI^)
echo     python geopackage_creator.py --help         ^(command-line help^)
echo ============================================================
echo.

REM ---- 6. Hand control to the user in an interactive shell -------------------
cmd /k
