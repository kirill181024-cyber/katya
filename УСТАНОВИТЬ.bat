@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [KATYA] Создание виртуального окружения…
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Не найден Python. Установите Python 3.10+ с python.org
    pause
    exit /b 1
  )
)

echo [KATYA] Обновление pip…
".venv\Scripts\python.exe" -m pip install --upgrade pip

echo [KATYA] Установка зависимостей…
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Ошибка установки зависимостей. Проверьте интернет и Python 3.10+.
  pause
  exit /b 1
)

echo [KATYA] Запуск Hardware-Adaptive установщика…
".venv\Scripts\python.exe" setup_wizard.py
endlocal
