@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" tools\startup.py disable
pause
