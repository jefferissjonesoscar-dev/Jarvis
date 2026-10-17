@echo off
cd /d "%~dp0"
title Jarvis
if not exist ".venv\Scripts\python.exe" (
  echo Setting up Python for Jarvis, one moment...
  py -m venv .venv || python -m venv .venv
)
echo Checking Jarvis is up to date...
".venv\Scripts\python" -m pip install -q --disable-pip-version-check -r requirements.txt
".venv\Scripts\python" -m jarvis
echo.
echo Jarvis has stopped. If you see an error above, copy it and send it to Claude.
pause
