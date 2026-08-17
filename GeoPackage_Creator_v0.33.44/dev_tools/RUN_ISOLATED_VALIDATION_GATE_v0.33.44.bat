@echo off
REM SPDX-License-Identifier: GPL-2.0-or-later
REM Run from Anaconda Prompt after: conda activate geopackage
setlocal EnableExtensions
cd /d "%~dp0.."
python dev_tools\verify_isolated_validation_v0.33.44.py
set "RC=%ERRORLEVEL%"
echo.
echo Send the newest dev_tools\logs\verify_isolated_validation_v0.33.44_*.log file.
endlocal & exit /b %RC%
