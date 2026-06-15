@echo off
REM GeoPackage Creator - Automated Dependency Installation
REM For Windows Command Prompt
REM Run as Administrator for best results

echo.
echo ========================================
echo GeoPackage Creator - Installation
echo ========================================
echo.

REM Step 1: Install Python packages
echo [1/2] Installing Python packages...
echo Installing: lxml
python -m pip install --upgrade pip
python -m pip install "lxml>=4.9.0"

if %ERRORLEVEL% equ 0 (
    echo.
    echo [OK] lxml installed successfully
) else (
    echo.
    echo [ERROR] Failed to install lxml
    pause
    exit /b 1
)

echo.

REM Step 2: Install GDAL
echo [2/2] Installing GDAL...
echo This may take a few moments...

REM Try conda first
where conda >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Conda detected. Installing GDAL via conda-forge...
    conda install -c conda-forge gdal -y
    if %ERRORLEVEL% equ 0 (
        goto success
    )
)

REM Try pip
echo Attempting to install GDAL via pip...
python -m pip install "GDAL>=3.6.0"

if %ERRORLEVEL% equ 0 (
    goto success
) else (
    goto manual_install
)

:success
echo.
echo ========================================
echo [SUCCESS] Installation Complete!
echo ========================================
echo.
echo All dependencies installed. Run:
echo   python geopackage_creator_gui.py
echo.
pause
exit /b 0

:manual_install
echo.
echo ========================================
echo [WARNING] GDAL Installation Failed
echo ========================================
echo.
echo GDAL requires system dependencies. Use one of these methods:
echo.
echo Option A: OSGeo4W (Recommended for Windows)
echo   Download: https://trac.osgeo.org/osgeo4w/
echo   Select GDAL during installation
echo.
echo Option B: Conda (Recommended for Python)
echo   Download: https://docs.conda.io/projects/miniconda/
echo   Then run: conda install -c conda-forge gdal
echo.
echo Option C: Pre-built Wheels
echo   Visit: https://www.lfd.uci.edu/~gohlke/pythonlibs/
echo   Search for GDAL wheel for your Python version
echo.
echo ========================================
echo.
pause
exit /b 1
