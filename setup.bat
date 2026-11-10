@echo off
rem SPDX-License-Identifier: Apache-2.0
rem One-off setup: creates .venv and installs the Python dependencies.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv ...
  python -m venv .venv || (echo Could not create .venv - is Python 3.11+ on PATH? & pause & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt pytest || (echo pip install failed. & pause & exit /b 1)
echo.
echo Python side done. Still needed (see README "Windows setup"):
echo   - a General MIDI .sf2 in soundfonts\
echo   - the FluidSynth Windows x64 DLLs in fluidsynth\
echo   - ffmpeg and ffprobe on PATH
echo Then run test.bat.
pause
