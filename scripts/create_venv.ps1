\
# scripts\create_venv.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Definition)
Set-Location ..
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt
Write-Host "Entorno creado. Para activar: .\.venv\Scripts\Activate.ps1"
