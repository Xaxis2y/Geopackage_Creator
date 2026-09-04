# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 Eui Soo SON
# GeoPackage Creator - Automated Dependency Installation
# For Windows PowerShell
# Run as Administrator

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "GeoPackage Creator - Installation Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
if (-not $isAdmin) {
    Write-Host "WARNING: This script should ideally run as Administrator for best results." -ForegroundColor Yellow
    Write-Host "You may be prompted for elevated permissions during GDAL installation." -ForegroundColor Yellow
    Write-Host ""
}

# Step 1: Install Python dependencies (lxml)
Write-Host "[1/4] Installing Python packages..." -ForegroundColor Green
Write-Host "Installing: lxml" -ForegroundColor White
python -m pip install --upgrade pip
python -m pip install "lxml>=4.9.0"

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ lxml installed successfully" -ForegroundColor Green
} else {
    Write-Host "✗ Failed to install lxml" -ForegroundColor Red
}

Write-Host ""

# Step 2: Install GUI theming (pip only - not on conda-forge, see
# requirements.txt / environment.yml for why)
Write-Host "[2/4] Installing GUI theming (ttkbootstrap)..." -ForegroundColor Green
python -m pip install "ttkbootstrap==2.2.0"

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ ttkbootstrap installed successfully" -ForegroundColor Green
} else {
    Write-Host "✗ Failed to install ttkbootstrap - the GUI will not start without it" -ForegroundColor Red
    Write-Host "  Retry later with: python -m pip install ""ttkbootstrap==2.2.0""" -ForegroundColor Yellow
}

Write-Host ""

# Step 3: Try to install GDAL via conda first (if available)
Write-Host "[3/4] Installing GDAL..." -ForegroundColor Green

# Check if conda is available
$condaPath = where.exe conda 2>$null
if ($condaPath) {
    Write-Host "Conda detected. Installing GDAL via conda-forge..." -ForegroundColor Cyan
    conda install -c conda-forge gdal=3.13.2 -y

    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ GDAL installed successfully via conda" -ForegroundColor Green
        Write-Host ""
        Write-Host "[4/4] Installation Complete!" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "All dependencies installed successfully!" -ForegroundColor Green
        Write-Host "You can now run: python geopackage_creator_gui.py" -ForegroundColor Cyan
        Write-Host "========================================" -ForegroundColor Cyan
        exit 0
    }
}

# If conda fails or not available, try pip with pre-built wheels
Write-Host "Attempting to install GDAL via pip with pre-built wheels..." -ForegroundColor Cyan
python -m pip install "GDAL==3.13.2"

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ GDAL installed successfully via pip" -ForegroundColor Green
    Write-Host ""
    Write-Host "[3/3] Installation Complete!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "All dependencies installed successfully!" -ForegroundColor Green
    Write-Host "You can now run: python geopackage_creator_gui.py" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    exit 0
}

# If both fail, provide manual instructions
Write-Host ""
Write-Host "⚠ GDAL installation via pip failed" -ForegroundColor Yellow
Write-Host ""
Write-Host "GDAL requires system dependencies and is complex to install on Windows." -ForegroundColor Yellow
Write-Host "Please use one of the following methods:" -ForegroundColor Yellow
Write-Host ""
Write-Host "Option A: Use OSGeo4W (Recommended for Windows)" -ForegroundColor Cyan
Write-Host "1. Download OSGeo4W from: https://trac.osgeo.org/osgeo4w/" -ForegroundColor White
Write-Host "2. Run the installer and select GDAL packages" -ForegroundColor White
Write-Host "3. Note the installation path (default: C:\OSGeo4W)" -ForegroundColor White
Write-Host ""
Write-Host "Option B: Use Conda (Recommended for Python)" -ForegroundColor Cyan
Write-Host "1. Download Miniconda from: https://docs.conda.io/projects/miniconda/en/latest/" -ForegroundColor White
Write-Host "2. Install Miniconda" -ForegroundColor White
Write-Host "3. Open Miniconda Prompt and run:" -ForegroundColor White
Write-Host "   conda install -c conda-forge gdal=3.13.2" -ForegroundColor White
Write-Host ""
Write-Host "Option C: Use Docker" -ForegroundColor Cyan
Write-Host "If you prefer containerized installation, Docker handles dependencies automatically." -ForegroundColor White
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "lxml has been installed successfully." -ForegroundColor Green
Write-Host "Please install GDAL using one of the options above." -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
