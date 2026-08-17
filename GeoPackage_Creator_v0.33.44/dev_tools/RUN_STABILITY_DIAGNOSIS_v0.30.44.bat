@echo off
REM SPDX-License-Identifier: GPL-2.0-or-later
REM Windows/Anaconda launcher for the v0.30.44 native-crash diagnosis.
REM
REM Run this FROM an Anaconda Prompt after:
REM     conda activate geopackage
REM
REM It deliberately does not activate or create an environment itself.  The
REM diagnostic must use the exact GDAL/lxml DLL combination that the product
REM uses on this machine.  The Python probe writes its own crash-resilient log
REM to dev_tools\logs\diagnose_v0.30.44_YYYYMMDD_HHMMSS.log.

setlocal EnableExtensions
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."

cd /d "%PROJECT_ROOT%"

echo.
echo ============================================================================
echo   GeoPackage Creator - Stability Diagnosis v0.30.44
echo ============================================================================
echo.
echo Active Python:
where python
if errorlevel 1 (
    echo.
    echo ERROR: python was not found. Open Anaconda Prompt, run
    echo        conda activate geopackage
    echo then run this launcher again.
    exit /b 1
)

python -c "import sys; print(sys.executable)"
if errorlevel 1 exit /b %errorlevel%

echo.
echo Starting four isolated probes. A native access violation in a probe is
echo expected to be captured by the parent script; do not close this window.
echo.
python "%SCRIPT_DIR%diagnose_crash_v0.30.44.py"
set "RESULT=%ERRORLEVEL%"

echo.
if "%RESULT%"=="0" (
    echo Diagnosis completed. Send the newest file matching:
    echo   dev_tools\logs\diagnose_v0.30.44_*.log
) else (
    echo Diagnosis finished with exit code %RESULT%.
    echo Send the newest file matching:
    echo   dev_tools\logs\diagnose_v0.30.44_*.log
)

endlocal & exit /b %RESULT%
