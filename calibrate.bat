@echo off
cd /d "%~dp0"
rem One-off: pre-measure streaming loudness for every mood with your SoundFont (takes about a minute)
".venv\Scripts\python.exe" -m bgmstudio.cli calibrate
pause
