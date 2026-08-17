@echo off
REM SPDX-License-Identifier: GPL-2.0-or-later
REM Copyright (c) 2026 Eui Soo SON
REM ===========================================================================
REM  GeoPackage Creator v0.33.44 - Windows build launcher
REM  Requires: GDAL 3.13.2 (conda-forge), Python 3.11, PyInstaller 6.x
REM  Thin wrapper around build_windows.ps1. Double-click or run from a prompt.
REM
REM  Usage:
REM     build_windows.bat                 (build both one-dir and one-file)
REM     build_windows.bat -OneFileOnly    (single .exe only)
REM     build_windows.bat -UseCurrentEnv  (skip conda; use active Python+GDAL)
REM ===========================================================================
setlocal
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%build_windows.ps1" %*
set RC=%ERRORLEVEL%
if %RC% NEQ 0 (
    echo.
    echo Build FAILED with exit code %RC%.
) else (
    echo.
    echo Build finished. See the dist\ folder.
)
pause
exit /b %RC%
