@echo off
REM ============================================================
REM  DGIWG GeoPackage Compliance Validator v1.63
REM  Step 2 of 2 - Build the standalone .exe
REM
REM  Run 01_create_environment.bat FIRST. Then run this by
REM  double-clicking it, OR from an Anaconda Prompt:
REM      02_build_exe.bat
REM
REM  What it does:
REM    1. Activates the "dgiwg" environment
REM    2. Confirms pyinstaller is installed (installs it if missing)
REM    3. Cleans any previous build\ and dist\ output
REM    4. Runs PyInstaller against DGIWG_Validator.spec
REM    5. Smoke-tests the resulting exe with --version
REM    6. Writes a full log to build_exe_log_<timestamp>.txt in this folder
REM
REM  Output:
REM    dist\DGIWG_Validator_v1_63.exe
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

for /f "usebackq tokens=1-6 delims=/:. " %%a in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"`) do set TS=%%a
set LOG=build_exe_log_%TS%.txt

echo ============================================================ > "%LOG%"
echo  DGIWG exe build log - %DATE% %TIME%                          >> "%LOG%"
echo ============================================================ >> "%LOG%"

echo.
echo ============================================================
echo  DGIWG GeoPackage Validator - Build EXE
echo ============================================================
echo.
echo Log file: %LOG%
echo.

echo [1/6] Activating "dgiwg" environment ...
echo [1/6] Activating "dgiwg" environment ... >> "%LOG%"
call conda activate dgiwg 2>>"%LOG%"
if errorlevel 1 (
    echo   ERROR: could not activate "dgiwg".
    echo   Run 01_create_environment.bat first, from an Anaconda Prompt.
    echo   ERROR: could not activate "dgiwg". >> "%LOG%"
    pause
    exit /b 1
)
python --version >> "%LOG%" 2>&1
echo   OK.

echo.
echo [2/6] Checking PyInstaller is installed ...
echo [2/6] Checking PyInstaller is installed ... >> "%LOG%"
python -c "import PyInstaller; print(PyInstaller.__version__)" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo   Not found - installing pyinstaller into "dgiwg" ...
    echo   Not found - installing pyinstaller into "dgiwg" ... >> "%LOG%"
    pip install "pyinstaller>=6.0" >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo   ERROR: pip install pyinstaller failed - see %LOG%.
        echo   ERROR: pip install pyinstaller failed. >> "%LOG%"
        pause
        exit /b 1
    )
)
echo   OK - PyInstaller ready.
echo   OK - PyInstaller ready. >> "%LOG%"

echo.
echo [3/6] Checking required source files are present ...
echo [3/6] Checking required source files are present ... >> "%LOG%"
if not exist "DGIWG_Validator_v1_63.py" (
    echo   ERROR: DGIWG_Validator_v1_63.py not found in this folder.
    echo   ERROR: DGIWG_Validator_v1_63.py not found. >> "%LOG%"
    pause
    exit /b 1
)
if not exist "dgiwg_validator\__init__.py" (
    echo   ERROR: dgiwg_validator\ package not found in this folder.
    echo   ERROR: dgiwg_validator\ package not found. >> "%LOG%"
    pause
    exit /b 1
)
if not exist "DGIWG_Validator.spec" (
    echo   ERROR: DGIWG_Validator.spec not found in this folder.
    echo   ERROR: DGIWG_Validator.spec not found. >> "%LOG%"
    pause
    exit /b 1
)
echo   OK - all required files present.
echo   OK - all required files present. >> "%LOG%"

echo.
echo [4/6] Cleaning previous build\ and dist\ output ...
echo [4/6] Cleaning previous build\ and dist\ output ... >> "%LOG%"
if exist "build" rmdir /s /q "build" 2>>"%LOG%"
if exist "dist\DGIWG_Validator_v1_63.exe" del /f /q "dist\DGIWG_Validator_v1_63.exe" 2>>"%LOG%"
echo   OK.

echo.
echo [5/6] Running PyInstaller ^(this can take a few minutes^) ...
echo [5/6] Running PyInstaller ... >> "%LOG%"
pyinstaller --clean --noconfirm DGIWG_Validator.spec >> "%LOG%" 2>&1
if errorlevel 1 (
    echo   ERROR: PyInstaller build failed - see %LOG% for the full trace.
    echo   ERROR: PyInstaller build failed. >> "%LOG%"
    echo.
    echo   Common causes:
    echo     - Antivirus quarantined a temp file mid-build ^(re-run, or add
    echo       an exclusion for this folder^)
    echo     - "Access is denied" on dist\ - close any running copy of the
    echo       exe first, then re-run this script
    pause
    exit /b 1
)

if not exist "dist\DGIWG_Validator_v1_63.exe" (
    echo   ERROR: build finished but dist\DGIWG_Validator_v1_63.exe was not
    echo   created - see %LOG%.
    echo   ERROR: exe not found after build. >> "%LOG%"
    pause
    exit /b 1
)
echo   OK - dist\DGIWG_Validator_v1_63.exe created.
echo   OK - dist\DGIWG_Validator_v1_63.exe created. >> "%LOG%"

echo.
echo [6/6] Smoke-testing the exe ^(--version^) ...
echo [6/6] Smoke-testing the exe ^(--version^) ... >> "%LOG%"
"dist\DGIWG_Validator_v1_63.exe" --version >> "%LOG%" 2>&1
if errorlevel 1 (
    echo   WARNING: the exe did not run cleanly with --version - see %LOG%.
    echo   It may still work for real files; check the log for the exact error.
) else (
    echo   OK - exe launches and reports its version correctly.
)

for %%F in ("dist\DGIWG_Validator_v1_63.exe") do set EXESIZE=%%~zF
echo   exe size: %EXESIZE% bytes >> "%LOG%"

echo.
echo ============================================================
echo  Build complete.
echo  EXE      : %cd%\dist\DGIWG_Validator_v1_63.exe
echo  Log file : %LOG%
echo.
echo  Try it now:
echo    dist\DGIWG_Validator_v1_63.exe --help
echo    dist\DGIWG_Validator_v1_63.exe path\to\file.gpkg
echo    dist\DGIWG_Validator_v1_63.exe            ^(opens file picker^)
echo ============================================================
echo.
pause
endlocal
