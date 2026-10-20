@echo off
title Katya 2.10 - Hyper-Drive
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Katya is not installed yet. Running installer...
  call install.bat
  exit /b 0
)
start "" ".venv\Scripts\pythonw.exe" "main.py"
exit /b 0
