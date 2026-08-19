@echo off
setlocal EnableExtensions
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Run this from an Anaconda Prompt after: conda activate dgiwg
REM It never modifies any GeoPackage; it writes only logs, test fixtures,
REM reports, and the distributable archive inside this release folder.
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
for /f %%I in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyyMMdd_HHmmss')"') do set "STAMP=%%I"
set "LOG=anaconda_validation_%STAMP%.log"

echo DGIWG GeoPackage Validator v1.62 validation > "%LOG%"
echo Started: %DATE% %TIME% >> "%LOG%"
echo. >> "%LOG%"

echo [1/5] Python and dependency probe
python --version >> "%LOG%" 2>&1
python -c "import PIL,lxml,pyproj,shapely; print('Pillow',PIL.__version__); print('lxml',lxml.__version__); print('pyproj',pyproj.__version__); print('shapely',shapely.__version__)" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo Missing dependencies. Install with: pip install -r requirements.txt
  echo Missing dependencies. Install with: pip install -r requirements.txt >> "%LOG%"
  goto :failed
)

echo [2/5] Bytecode compilation
python -m compileall -q dgiwg_validator >> "%LOG%" 2>&1
if errorlevel 1 goto :failed

echo [3/5] CLI smoke test
python -m dgiwg_validator --version >> "%LOG%" 2>&1
python -m dgiwg_validator --help >> "%LOG%" 2>&1
if errorlevel 1 goto :failed

echo [4/5] Regression suite
python run_local_tests.py >> "%LOG%" 2>&1
if errorlevel 1 goto :failed

echo [5/5] Release package integrity
python package_release.py >> "%LOG%" 2>&1
if errorlevel 1 goto :failed

echo. >> "%LOG%"
echo RESULT: PASS >> "%LOG%"
echo Completed successfully. Log: %CD%\%LOG%
type "%LOG%"
exit /b 0

:failed
echo. >> "%LOG%"
echo RESULT: FAIL >> "%LOG%"
echo Validation failed. Send this log for review: %CD%\%LOG%
type "%LOG%"
exit /b 1

