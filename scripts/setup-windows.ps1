$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Install Python 3.12 (64-bit), including the py launcher." }
}
& .venv\Scripts\python.exe -m pip install -r requirements-windows.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& .venv\Scripts\python.exe -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw "Project installation failed." }
if (-not (Test-Path "local\config.json")) {
    & .venv\Scripts\mxd-jev.exe init
    if ($LASTEXITCODE -ne 0) { throw "Configuration initialization failed." }
}
Write-Host "Ready. Edit local\config.json, then follow docs\WINDOWS.md."
