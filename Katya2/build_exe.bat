@echo off
chcp 65001 >nul
title Katya 2.10.1 - build
echo ==================================================
echo   Сборка версии Кати 2.10.1 в один клик...
echo ==================================================
echo.

pyinstaller --noconfirm --onefile --windowed ^
  --name Katya_2.10.1_Setup ^
  --add-data "core;core" ^
  --add-data "skills;skills" ^
  --add-data "config.py;." ^
  --add-data "gui.py;." ^
  --add-data "requirements.txt;." ^
  --add-data "banner.svg;." ^
  --add-data "katya.ico;." ^
  --collect-all customtkinter ^
  --collect-all vosk ^
  --collect-all edge_tts ^
  setup_wizard.py

echo.
echo Сборка завершена! Готовый дистрибутив лежит в папке dist/.
echo Переименуй dist\Katya_2.10.1_Setup.exe при необходимости.
pause
