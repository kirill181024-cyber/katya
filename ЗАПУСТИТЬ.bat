@echo off
cd /d "%~dp0"
if not exist "Katya2\.venv\Scripts\pythonw.exe" (
  echo Не найден venv: Katya2\.venv\Scripts\pythonw.exe
  echo Сначала установи зависимости: Katya2\.venv\Scripts\python.exe -m pip install -r Katya2\requirements.txt
  pause
  exit /b 1
)
start "" "Katya2\.venv\Scripts\pythonw.exe" "Katya2\main.py"
exit /b 0
