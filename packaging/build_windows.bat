@echo off
REM ===========================================================================
REM  GeoPackage Creator - Windows build launcher
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
