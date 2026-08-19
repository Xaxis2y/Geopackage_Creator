@echo off
REM SPDX-License-Identifier: GPL-2.0-or-later
REM Copyright (c) 2026 Eui Soo SON
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Validate a real GeoPackage folder from an Anaconda Prompt.
REM Usage: run_real_geopackage_validation.bat [INPUT_FOLDER]
REM Default input: ..\geopackages
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
if "%~1"=="" (set "INPUT=%SCRIPT_DIR%..\geopackages") else (set "INPUT=%~1")
for /f %%I in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyyMMdd_HHmmss')"') do set "STAMP=%%I"
set "OUTPUT=%INPUT%\reports_v162_%STAMP%"
set "LOG=%SCRIPT_DIR%real_validation_%STAMP%.log"

echo DGIWG GeoPackage Validator v1.62 real-data validation > "%LOG%"
echo Input: %INPUT% >> "%LOG%"
echo Output: %OUTPUT% >> "%LOG%"
echo. >> "%LOG%"
python --version >> "%LOG%" 2>&1
python -c "import PIL,lxml,pyproj,shapely; print('Pillow',PIL.__version__); print('lxml',lxml.__version__); print('pyproj',pyproj.__version__); print('shapely',shapely.__version__)" >> "%LOG%" 2>&1
if errorlevel 1 goto :failed

python -m dgiwg_validator --offline --no-install --recursive --output-dir "%OUTPUT%" "%INPUT%" >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo. >> "%LOG%"
echo Validator exit code: %RC% >> "%LOG%"
echo Log: %LOG%
type "%LOG%"
exit /b %RC%

:failed
echo RESULT: FAIL >> "%LOG%"
echo Dependency probe failed. Install requirements with: pip install -r requirements.txt >> "%LOG%"
type "%LOG%"
exit /b 2
