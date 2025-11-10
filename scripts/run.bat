@echo off
REM scripts\run.bat
cd /d %~dp0
cd ..
.\.venv\Scripts\python.exe etl_inventario.py
