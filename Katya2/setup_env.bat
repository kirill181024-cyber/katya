@echo off
title Katya 2.10 - Hyper-Drive
cd /d "%~dp0"
chcp 65001 >nul

if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "main.py"
  exit /b 0
)

echo ================================================
echo    KATYA 2.10 - first-run setup
echo    Creating the Python environment (1-3 min)
echo ================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found in PATH.
  echo Install Python 3.11+ from https://www.python.org/downloads/
  echo and check "Add Python to PATH", then run Katya again.
  echo.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)

echo Creating virtual environment ...
python -m venv .venv
if errorlevel 1 (
  echo [ERROR] Failed to create the environment.
  pause
  exit /b 1
)

echo Installing dependencies ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check >nul 2>nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to install dependencies. Check your internet connection.
  pause
  exit /b 1
)

echo.
echo Done! Installing Ollama is still required once:
echo   https://ollama.com/download  then:  ollama pull qwen2.5:7b
echo.
echo Starting Katya ...
start "" ".venv\Scripts\pythonw.exe" "main.py"
exit /b 0
