@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Python virtual environment is missing. Run setup.bat first.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" bgm_gui.py
if errorlevel 1 pause
