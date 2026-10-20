@echo off
title Katya 2.10 - Install
cd /d "%~dp0"
chcp 65001 >nul

echo ================================================
echo    KATYA 2.10 - HYPER-DRIVE    INSTALL
echo ================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found.
  echo.
  echo Install Python 3.11+ from https://www.python.org/downloads/
  echo IMPORTANT: check "Add Python to PATH" during setup, then run this file again.
  echo.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)

echo [1/4] Creating virtual environment .venv ...
if not exist ".venv\Scripts\pythonw.exe" (
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create venv.
    pause
    exit /b 1
  )
) else (
  echo       already exists, skipping.
)

echo [2/4] Upgrading pip ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check >nul

echo [3/4] Installing dependencies (this takes 1-3 minutes) ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo [ERROR] Failed to install dependencies. Check your internet connection.
  pause
  exit /b 1
)

echo [4/4] Creating shortcuts ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make_shortcut.ps1"

echo.
echo ================================================
echo   DONE!  Shortcut "Katya 2.10" created.
echo   You can now run Katya from the desktop.
echo ================================================
echo.

where ollama >nul 2>nul
if errorlevel 1 (
  echo [NOTE] Ollama not found. Katya needs it for the AI brain.
  echo        Download: https://ollama.com/download
  echo        After install, open a console and run:  ollama pull qwen2.5:7b
  echo.
)

echo Starting Katya now ...
start "" ".venv\Scripts\pythonw.exe" "main.py"
timeout /t 2 >nul
exit /b 0
