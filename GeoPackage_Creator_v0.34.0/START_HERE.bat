@echo off
REM SPDX-License-Identifier: GPL-2.0-or-later
REM Copyright (c) 2026 Eui Soo SON
setlocal enabledelayedexpansion

REM GeoPackage Creator - Simple Launcher v0.34

REM Always run from this script's own folder so 'core' imports resolve
cd /d "%~dp0"

REM Use the Anaconda Python that has GDAL/osgeo installed.
REM Plain cmd.exe defaults to a system Python without osgeo, which fails.
set "PYTHON=C:\ProgramData\anaconda3\python.exe"
if not exist "%PYTHON%" (
    echo WARNING: Anaconda Python not found at "%PYTHON%".
    echo Falling back to 'python' on PATH ^(run from an Anaconda Prompt^).
    set "PYTHON=python"
)

:menu
cls
echo.
echo ================================================================================
echo  GeoPackage Creator v0.34
echo ================================================================================
echo.
echo What would you like to do?
echo.
echo  1) Open GUI (Easy - Graphical Interface)
echo  2) Convert via Command Line
echo  3) Exit
echo.
set /p choice="Enter your choice (1-3): "

if "!choice!"=="1" (
    goto gui_launcher
) else if "!choice!"=="2" (
    goto convert
) else if "!choice!"=="3" (
    goto exit_menu
) else (
    echo.
    echo Invalid choice. Please try again.
    echo.
    pause
    goto menu
)

:gui_launcher
cls
echo.
echo ================================================================================
echo  GeoPackage Creator - GUI Launcher
echo ================================================================================
echo.
echo Launching GUI application...
echo.

"%PYTHON%" geopackage_creator_gui.py

if !errorlevel! neq 0 (
    echo.
    echo ================================================================================
    echo Error: GUI failed to launch!
    echo ================================================================================
    echo.
    echo This usually means GDAL/osgeo is not available to this Python.
    echo Using: %PYTHON%
    echo Make sure dependencies are installed:
    echo   pip install -r requirements.txt
    echo.
)

pause
goto menu

:convert
cls
echo.
echo ================================================================================
echo  GeoPackage Conversion
echo ================================================================================
echo.
echo Please enter the path to your GeoDatabase or Shapefile.
echo.
echo Example: C:\Users\YourName\Documents\data\buildings.gdb
echo.
set /p source="Enter source file path (.gdb or .shp): "

if "!source!"=="" (
    echo.
    echo Source file cannot be empty!
    echo.
    pause
    goto menu
)

if not exist "!source!" (
    echo.
    echo Error: File not found - !source!
    echo.
    pause
    goto menu
)

echo Selected: !source!
echo.
set /p output="Enter output file path .gpkg: "

if "!output!"=="" (
    echo.
    echo Output file path cannot be empty!
    echo.
    pause
    goto menu
)

echo.
set /p title="Enter dataset title: "

if "!title!"=="" (
    echo.
    echo Title cannot be empty!
    echo.
    pause
    goto menu
)

echo.
set /p org="Enter organization name: "

if "!org!"=="" (
    echo.
    echo Organization cannot be empty!
    echo.
    pause
    goto menu
)

echo.
set /p nation="Enter nation code USA, GBR, DEU, FRA, etc.: "

if "!nation!"=="" (
    echo.
    echo Nation code cannot be empty!
    echo.
    pause
    goto menu
)

echo.
echo ================================================================================
echo Running conversion...
echo ================================================================================
echo.

"%PYTHON%" geopackage_creator.py --source "!source!" --output "!output!" --title "!title!" --org "!org!" --nation "!nation!"

if !errorlevel! equ 0 (
    echo.
    echo ================================================================================
    echo Conversion completed successfully!
    echo ================================================================================
    echo.
) else (
    echo.
    echo ================================================================================
    echo Error occurred during conversion!
    echo ================================================================================
    echo.
)

pause
goto menu

:exit_menu
cls
echo.
echo ================================================================================
echo  Thank you for using GeoPackage Creator v0.34!
echo ================================================================================
echo.
echo What would you like to do?
echo.
echo  1) Close command window
echo  2) Keep command window open
echo.
set /p exitchoice="Enter your choice (1-2): "

if "!exitchoice!"=="2" (
    echo.
    echo Command window will stay open. Type 'exit' to close it.
    cmd /k
) else (
    endlocal
    exit
)
