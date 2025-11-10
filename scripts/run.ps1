# scripts\run.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Definition)
Set-Location ..
.\.venv\Scripts\python.exe etl_inventario.py