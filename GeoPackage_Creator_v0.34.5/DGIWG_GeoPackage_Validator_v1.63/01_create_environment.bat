@echo off
REM ============================================================
REM  DGIWG GeoPackage Compliance Validator v1.63
REM  Step 1 of 2 — Create the Anaconda environment
REM
REM  Run this by double-clicking it, OR from an Anaconda Prompt:
REM      01_create_environment.bat
REM
REM  What it does:
REM    1. Confirms conda is available
REM    2. Creates (or updates) a dedicated "dgiwg" environment from
REM       environment.yml — never touches the "base" environment
REM    3. Installs: python 3.11, shapely, Pillow, pyproj, lxml, pyinstaller
REM    4. Runs the 84-assertion self-test suite to confirm the install works
REM    5. Writes a full log to env_setup_log_<timestamp>.txt in this folder
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM Build a sortable timestamp (YYYYMMDD_HHMMSS) independent of locale
for /f "usebackq tokens=1-6 delims=/:. " %%a in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"`) do set TS=%%a
set LOG=env_setup_log_%TS%.txt

echo ============================================================ > "%LOG%"
echo  DGIWG environment setup log - %DATE% %TIME%                  >> "%LOG%"
echo ============================================================ >> "%LOG%"

echo.
echo ============================================================
echo  DGIWG GeoPackage Validator - Environment Setup
echo ============================================================
echo.
echo Log file: %LOG%
echo.

echo [1/5] Checking conda is available ...
echo [1/5] Checking conda is available ... >> "%LOG%"
where conda >nul 2>&1
if errorlevel 1 (
    echo   ERROR: conda was not found on PATH.
    echo   ERROR: conda was not found on PATH. >> "%LOG%"
    echo   Open "Anaconda Prompt" from the Start Menu instead of a plain
    echo   Command Prompt, then re-run this script.
    echo   Open "Anaconda Prompt" from the Start Menu instead of a plain Command Prompt, then re-run this script. >> "%LOG%"
    pause
    exit /b 1
)
conda --version >> "%LOG%" 2>&1
echo   OK - conda found.
echo   OK - conda found. >> "%LOG%"

echo.
echo [2/5] Creating/updating the "dgiwg" environment from environment.yml ...
echo [2/5] Creating/updating the "dgiwg" environment from environment.yml ... >> "%LOG%"
echo   Trying "conda env create" first (fresh environment) ... >> "%LOG%"
call conda env create -f environment.yml >> "%LOG%" 2>&1
if errorlevel 1 (
    echo   "dgiwg" likely already exists - updating it in place instead ...
    echo   create failed (likely already exists) - trying "conda env update" instead ... >> "%LOG%"
    call conda env update -n dgiwg -f environment.yml --prune >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo   ERROR: environment create/update both failed - see %LOG% for details.
        echo   ERROR: environment create/update both failed. >> "%LOG%"
        pause
        exit /b 1
    )
)
echo   OK - environment ready.
echo   OK - environment ready. >> "%LOG%"

echo.
echo [3/5] Activating "dgiwg" and confirming Python + key packages ...
echo [3/5] Activating "dgiwg" and confirming Python + key packages ... >> "%LOG%"
call conda activate dgiwg
if errorlevel 1 (
    echo   ERROR: could not activate "dgiwg" - see %LOG%.
    echo   ERROR: could not activate "dgiwg". >> "%LOG%"
    pause
    exit /b 1
)
python --version >> "%LOG%" 2>&1
python -c "import shapely, PIL, pyproj, lxml, PyInstaller; print('shapely   :', shapely.__version__); print('Pillow    :', PIL.__version__); print('pyproj    :', pyproj.__version__); print('lxml      :', lxml.etree.LXML_VERSION); print('PyInstaller:', PyInstaller.__version__)" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo   WARNING: one or more packages failed to import - see %LOG%.
    echo   The validator still runs without them ^(reduced coverage^), but the
    echo   .exe build step needs pyinstaller at minimum.
) else (
    echo   OK - all packages import cleanly.
)

echo.
echo [4/5] Running the 84-assertion self-test suite ...
echo [4/5] Running the 84-assertion self-test suite ... >> "%LOG%"
python run_local_tests.py >> "%LOG%" 2>&1
findstr /c:"ALL TESTS PASSED" "%LOG%" >nul 2>&1
if errorlevel 1 (
    echo   WARNING: self-test did not report ALL TESTS PASSED - see %LOG%
    echo   and the local_test_log_*.txt file it generated for details.
) else (
    echo   OK - all 84 assertions passed.
)

echo.
echo [5/5] Done.
echo [5/5] Done. >> "%LOG%"
echo.
echo ============================================================
echo  Environment "dgiwg" is ready.
echo  Full details were written to: %LOG%
echo.
echo  Next step: run 02_build_exe.bat to build the standalone .exe.
echo ============================================================
echo.
pause
endlocal
