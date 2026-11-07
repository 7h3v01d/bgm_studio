@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo .venv not found. Run setup.bat first.
  pause
  exit /b 1
)
rem ---- optional settings (remove "rem" to use) ----
rem set BGM_API_KEY=change-me
rem set BGM_SOUNDFONT=%~dp0soundfonts\FluidR3_GM.sf2
rem set BGM_OUT_DIR=%~dp0bgm_out
rem set FLUIDSYNTH_DIR=%~dp0fluidsynth\bin
echo bgmstudio listening on http://127.0.0.1:8765   (interactive docs: http://127.0.0.1:8765/docs)
echo Close this window to stop it.
".venv\Scripts\python.exe" -m uvicorn bgmstudio.api:app --host 127.0.0.1 --port 8765
pause
