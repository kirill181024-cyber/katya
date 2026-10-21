@echo off
chcp 65001 >nul
title Katya 2.10 - Anti-Alice Swarm Edition
cd /d "%~dp0"

echo ==================================================
echo    KATYA 2.10 - ANTI-ALICE SWARM EDITION
echo    local AI agent: self-coding + Cyber-Coach
echo ==================================================
echo.

rem ---------- Python ----------
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.11+ from python.org
  echo         and check "Add Python to PATH", then run this file again.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)

rem ---------- Ollama ----------
where ollama >nul 2>nul
if errorlevel 1 (
  echo [1/5] Ollama not found. Opening the download page ...
  echo       Install it, then run this file again.
  start "" https://ollama.com/download
  pause
  exit /b 1
)
echo [1/5] Ollama found.

rem ---------- venv ----------
if not exist ".venv\Scripts\pythonw.exe" (
  echo [2/5] Creating virtual environment ...
  python -m venv .venv
) else (
  echo [2/5] Virtual environment already exists.
)

rem ---------- deps ----------
echo [3/5] Installing dependencies ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check >nul 2>nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo [ERROR] Failed to install dependencies. Check your internet connection.
  pause
  exit /b 1
)

rem ---------- models ----------
echo [4/5] Pulling AI model (gemma3:4b, runs on GPU). This can take a while ...
ollama pull gemma3:4b

rem ---------- run ----------
echo [5/5] Launching Katya ...
start "" ".venv\Scripts\pythonw.exe" "main.py"
exit /b 0
