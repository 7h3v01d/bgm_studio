@echo off
rem SPDX-License-Identifier: Apache-2.0
rem Runs the regression tests (fast) and then the full end-to-end selftest (~2 minutes).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo .venv not found. Run setup.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pytest -q || (echo. & echo REGRESSION TESTS FAILED & pause & exit /b 1)
".venv\Scripts\python.exe" selftest.py
pause
