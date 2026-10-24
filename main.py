"""
Katya 2.11.0 — Marvel-Swarm Edition
Entry point.

Usage:
    python main.py            # launch HUD
    python main.py --setup    # hardware-adaptive installer
    python main.py --check    # diagnostic report, no GUI
    python main.py --version
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import platform
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import config

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging() -> None:
    config.ensure_runtime_dirs()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        return

    file_handler = RotatingFileHandler(
        config.LOG_DIR / "katya.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(file_handler)

    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(stream)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


DEPENDENCIES = {
    "customtkinter": "customtkinter",
    "psutil": "psutil",
    "PIL": "Pillow",
    "requests": "requests",
    "sounddevice": "sounddevice",
    "soundfile": "soundfile",
    "vosk": "vosk",
    "edge_tts": "edge-tts",
    "mss": "mss",
    "numpy": "numpy",
    "pycaw": "pycaw",
    "pyautogui": "pyautogui",
    "pywinauto": "pywinauto",
    "cv2": "opencv-python",
    "bs4": "beautifulsoup4",
    "yt_dlp": "yt-dlp",
}


def missing_dependencies() -> list[str]:
    return [package for module, package in DEPENDENCIES.items() if not _module_available(module)]


def run_check() -> int:
    configure_logging()
    report: dict[str, Any] = {
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "executable": sys.executable,
        "cwd": str(Path.cwd()),
        "data_dir": str(config.DATA_DIR),
        "ollama_url": config.OLLAMA_URL,
        "models": config.OLLAMA_MODELS,
        "github_repo": config.GITHUB_URL,
        "github_token_present": bool(config.GITHUB_TOKEN),
        "dependencies_missing": missing_dependencies(),
    }
    try:
        import psutil

        report["ram_gb"] = round(psutil.virtual_memory().total / (1024**3), 1)
        report["cpu_threads"] = psutil.cpu_count(logical=True)
    except Exception:
        report["ram_gb"] = None

    try:
        import requests

        response = requests.get(config.OLLAMA_TAGS_URL, timeout=3)
        report["ollama_online"] = response.status_code == 200
        if response.status_code == 200:
            report["ollama_models"] = [
                item.get("name") for item in response.json().get("models", [])
            ]
    except Exception as exc:
        report["ollama_online"] = False
        report["ollama_error"] = str(exc)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["dependencies_missing"] else 1


def _install_exception_hook() -> None:
    def hook(exc_type, exc_value, exc_tb) -> None:  # noqa: ANN001
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("katya").critical(
            "Unhandled exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        try:
            import tkinter.messagebox as messagebox

            messagebox.showerror(
                "Катя 2.11.0",
                f"Критическая ошибка:\n{exc_value}\n\nПодробности: {config.LOG_DIR / 'katya.log'}",
            )
        except Exception:
            pass

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Katya 2.11.0 Marvel-Swarm")
    parser.add_argument("--setup", action="store_true", help="запустить установщик")
    parser.add_argument("--check", action="store_true", help="диагностика без GUI")
    parser.add_argument("--version", action="store_true", help="версия")
    args = parser.parse_args(argv)

    if args.version:
        print(f"{config.APP_NAME} {config.APP_VERSION} — {config.CODENAME}")
        return 0
    if args.check:
        return run_check()
    if args.setup:
        configure_logging()
        from setup_wizard import main as setup_main

        return setup_main()

    if sys.version_info < (3, 10):
        print("Требуется Python 3.10 или новее.", file=sys.stderr)
        return 2

    configure_logging()
    _install_exception_hook()

    missing = missing_dependencies()
    if missing:
        message = (
            "Не установлены зависимости: "
            + ", ".join(missing)
            + "\n\nВыполните:\n  pip install -r requirements.txt\n"
            "или запустите setup_wizard.py"
        )
        print(message, file=sys.stderr)
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Катя 2.11.0 — не хватает библиотек", message)
            root.destroy()
        except Exception:
            pass
        return 2

    if os.name != "nt":
        print("Внимание: Win32-протоколы доступны только в Windows.", file=sys.stderr)

    logger = logging.getLogger("katya")
    logger.info("Запуск %s %s", config.APP_NAME, config.APP_VERSION)
    from ui.interface import run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
