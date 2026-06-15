<#
.SYNOPSIS
    Build GeoPackage Creator into a Windows application (.exe) with PyInstaller.

.DESCRIPTION
    Produces BOTH distribution layouts by default:
      1. One-dir build  -> dist\GeoPackageCreator\GeoPackageCreator.exe
                           (used by the Inno Setup installer)
      2. One-file build -> dist\GeoPackageCreator.exe
                           (single portable executable)

    GDAL is the critical dependency. The most reliable way to get a working
    `from osgeo import gdal` plus its gdal-data/proj-data is a conda-forge
    environment, so this script uses conda by default. If you already have a
    Python environment where `python -c "from osgeo import gdal"` succeeds,
    run with -UseCurrentEnv to skip conda.

.PARAMETER OneDirOnly
    Build only the one-dir layout (for the installer).

.PARAMETER OneFileOnly
    Build only the single-file .exe.

.PARAMETER UseCurrentEnv
    Use the currently active Python instead of creating/activating a conda env.

.PARAMETER EnvName
    Name of the conda environment to create/use (default: gpkgbuild).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -OneFileOnly
#>

param(
    [switch]$OneDirOnly,
    [switch]$OneFileOnly,
    [switch]$UseCurrentEnv,
    [string]$EnvName = "gpkgbuild"
)

$ErrorActionPreference = "Stop"

# ---- Resolve project root (parent of this script's folder) -----------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root
Write-Host "==> Project root: $Root" -ForegroundColor Cyan

# ---- Choose how to invoke Python --------------------------------------------
# IMPORTANT (Windows + conda): do NOT call the env's python.exe by full path
# while a different env (e.g. base) is still on PATH. Python will load the wrong
# libgdal/geos/proj DLLs and fail with
#   "ImportError: DLL load failed while importing _gdal: The specified
#    procedure could not be found."
# Running through `conda run -n <env>` properly deactivates base, activates the
# target env, and puts the correct DLLs first. --no-capture-output streams
# output live (needed so the long PyInstaller step doesn't look hung).
function Invoke-Py {
    param([string[]]$PyArgs)
    if ($script:UseConda) {
        & conda run --no-capture-output -n $script:EnvName python @PyArgs
    }
    else {
        & python @PyArgs
    }
    if ($LASTEXITCODE -ne 0) { throw "Command failed: python $($PyArgs -join ' ')" }
}

if ($UseCurrentEnv) {
    $script:UseConda = $false
    Write-Host "==> Using current Python environment" -ForegroundColor Cyan
}
else {
    # Create / reuse a conda env with GDAL from conda-forge.
    $conda = (Get-Command conda -ErrorAction SilentlyContinue)
    if (-not $conda) {
        throw "conda not found on PATH. Install Miniconda/Anaconda, or re-run with -UseCurrentEnv if your active Python already has GDAL."
    }
    $envExists = (& conda env list) -match "^\s*$EnvName\s"
    if (-not $envExists) {
        Write-Host "==> Creating conda env '$EnvName' with GDAL (conda-forge)..." -ForegroundColor Cyan
        & conda create -y -n $EnvName -c conda-forge python=3.11 gdal shapely pyproj lxml
        if ($LASTEXITCODE -ne 0) { throw "conda create failed" }
    }
    else {
        Write-Host "==> Reusing existing conda env '$EnvName'" -ForegroundColor Cyan
    }
    $script:UseConda = $true
    $script:EnvName = $EnvName
    Write-Host "==> Python: conda run -n $EnvName python" -ForegroundColor Cyan
}

# ---- Verify GDAL is importable ----------------------------------------------
Write-Host "==> Verifying GDAL import..." -ForegroundColor Cyan
Invoke-Py @("-c", "from osgeo import gdal; print('GDAL', gdal.__version__)")

# ---- Install build-time deps (PyInstaller + project deps) -------------------
Write-Host "==> Installing build dependencies..." -ForegroundColor Cyan
Invoke-Py @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Py @("-m", "pip", "install", "pyinstaller>=6.0")
# Note: shapely / pyproj / lxml / gdal come from the conda env (GDAL-linked
# builds). We deliberately do NOT pip-install them here so pip cannot overwrite
# conda's binaries with incompatible PyPI wheels. If you ran -UseCurrentEnv,
# make sure those packages are already present in that environment.

# ---- Clean previous output ---------------------------------------------------
foreach ($d in @("build", "dist")) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}

$Spec = "packaging\GeoPackageCreator.spec"

function Build-Variant {
    param([string]$OneFileFlag, [string]$Label)
    Write-Host ""
    Write-Host "==> Building $Label ..." -ForegroundColor Green
    $env:GPKG_ONEFILE = $OneFileFlag
    Invoke-Py @("-m", "PyInstaller", $Spec, "--noconfirm", "--clean")
}

if (-not $OneFileOnly) {
    Build-Variant "0" "one-dir layout (for installer)"
    # Preserve the one-dir output before the one-file build overwrites dist\.
    if (-not $OneDirOnly) {
        if (Test-Path "dist\GeoPackageCreator") {
            if (Test-Path "dist_onedir") { Remove-Item -Recurse -Force "dist_onedir" }
            New-Item -ItemType Directory -Force -Path "dist_onedir" | Out-Null
            Move-Item "dist\GeoPackageCreator" "dist_onedir\GeoPackageCreator"
        }
    }
}

if (-not $OneDirOnly) {
    Build-Variant "1" "single-file .exe"
}

# Restore the one-dir output alongside the one-file exe for convenience.
if ((-not $OneFileOnly) -and (-not $OneDirOnly) -and (Test-Path "dist_onedir\GeoPackageCreator")) {
    Move-Item "dist_onedir\GeoPackageCreator" "dist\GeoPackageCreator"
    Remove-Item -Recurse -Force "dist_onedir"
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host " Build complete. Outputs in: $Root\dist" -ForegroundColor Green
if (Test-Path "dist\GeoPackageCreator\GeoPackageCreator.exe") {
    Write-Host "   one-dir : dist\GeoPackageCreator\GeoPackageCreator.exe"
}
if (Test-Path "dist\GeoPackageCreator.exe") {
    Write-Host "   one-file: dist\GeoPackageCreator.exe"
}
Write-Host " Next (optional installer): compile packaging\installer\GeoPackageCreator.iss with Inno Setup." -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
