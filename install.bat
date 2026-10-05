@echo off
cd /d "%~dp0"
if not exist "config.yaml" (
  copy /y "config.example.yaml" "config.yaml" >nul
  if errorlevel 1 goto fail
)
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" tools\install.py
if errorlevel 1 goto fail
echo Installation complete. Double-click start.bat.
pause
exit /b 0
:fail
echo Installation failed. Please keep the error above for diagnosis.
pause
exit /b 1
