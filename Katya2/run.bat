@echo off
title Katya 2.10 - Hyper-Drive
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "main.py"
  exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1"
exit /b 0
