@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" selftest_client.py
pause
