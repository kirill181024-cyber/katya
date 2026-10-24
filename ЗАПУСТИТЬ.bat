@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "KATYA_PY=pythonw"
if exist ".venv\Scripts\pythonw.exe" set "KATYA_PY=.venv\Scripts\pythonw.exe"

start "" "%KATYA_PY%" "%~dp0main.py"
if errorlevel 1 (
  echo.
  echo Не удалось запустить Катю.
  echo Установите зависимости:  py -3 -m venv .venv
  echo                         .venv\Scripts\python -m pip install -r requirements.txt
  echo.
  pause
)
endlocal
