@echo off
rem Windows release verification: integrity, environment inventory, pytest, audio selftest.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [FAIL] .venv missing; run setup.bat first.
  exit /b 1
)
".venv\Scripts\python.exe" release_verify.py --capture-env --tests
if errorlevel 1 (
  echo [FAIL] Release verification failed.
  exit /b 1
)
echo [PASS] Release verification completed.
exit /b 0
