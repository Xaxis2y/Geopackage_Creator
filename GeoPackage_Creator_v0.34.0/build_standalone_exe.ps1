$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $project
$python = "C:\ProgramData\Anaconda3\python.exe"
& $python -m PyInstaller --noconfirm --clean --onefile `
  --name DGIWG_Validator_v1.62 `
  --paths . `
  --add-data "dgiwg_epsg_cache.json;." `
  --hidden-import pyproj `
  --hidden-import shapely `
  exe_entry.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
Write-Host "Built: $project\dist\DGIWG_Validator_v1.62.exe"
