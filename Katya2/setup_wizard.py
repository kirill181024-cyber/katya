"""Katya 2.10.1 — графический установщик (Setup Wizard).

Один файл, который сам:
  1) проверяет Python и библиотеки, при необходимости тихо доустанавливает;
  2) находит/устанавливает Ollama (тихая установка OllamaSetup.exe /silent);
  3) качает модель gemma3:4b (текст + зрение, работает на GPU) с прогресс-баром;
  4) тихо закрывается и запускает main.py.

Весь код обёрнут в try-except для «неубиваемости».
"""

import os
import re
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
MODEL = "gemma3:4b"
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_DOWNLOAD = "https://ollama.com/download/OllamaSetup.exe"

try:
    import requests
except Exception:
    requests = None

try:
    import customtkinter as ctk
except Exception:
    ctk = None


# ----------------------------------------------------------------------------
# Вспомогательные функции
# ----------------------------------------------------------------------------

def _python_exe():
    """Путь к python для фоновых pip-операций. None в exe-режиме (всё вшито)."""
    if getattr(sys, "frozen", False):
        return None
    cand = APP_DIR / ".venv" / "Scripts" / "python.exe"
    if cand.exists():
        return str(cand)
    return sys.executable


def _run(cmd, **kw):
    """Безопасный запуск команды. Возвращает (returncode, stdout)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, **kw)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def _find_ollama():
    """Ищет исполняемый файл ollama.exe."""
    try:
        import shutil
        exe = shutil.which("ollama")
        if exe:
            return exe
        for p in (
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Ollama" / "ollama.exe",
        ):
            if p.exists():
                return str(p)
    except Exception:
        pass
    return None


def _ollama_ready(timeout=120):
    """Ждёт, пока локальный сервер Ollama начнёт отвечать."""
    if requests is None:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(OLLAMA_URL + "/api/tags", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            time.sleep(2)
    return False


def _diag(msg):
    """Диагностический лог установщика в %TEMP%\\katya_setup.log."""
    try:
        p = Path(os.environ.get("TEMP", ".")) / "katya_setup.log"
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Графический установщик
# ----------------------------------------------------------------------------

class SetupWizard:
    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.app = ctk.CTk()
        self.app.title("Katya 2.10.1 — Установка")
        self.app.geometry("640x420")
        self.app.resizable(False, False)
        self.app.protocol("WM_DELETE_WINDOW", self._on_close)
        self.done = False
        self._should_launch = False
        self._build_ui()

    def _build_ui(self):
        bg = "#0B0E12"
        neon = "#22D3EE"
        green = "#34D399"
        self.app.configure(fg_color=bg)

        self.title_lbl = ctk.CTkLabel(
            self.app, text="KATYA 2.10.1",
            font=ctk.CTkFont(family="Segoe UI", size=34, weight="bold"),
            text_color=neon)
        self.title_lbl.pack(pady=(36, 4))

        self.sub_lbl = ctk.CTkLabel(
            self.app, text="Установка локального ИИ-агента",
            font=ctk.CTkFont(family="Segoe UI", size=15),
            text_color="#8FA3B0")
        self.sub_lbl.pack(pady=(0, 24))

        self.step_lbl = ctk.CTkLabel(
            self.app, text="Подготовка...",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#E6EDF3", wraplength=560, justify="left")
        self.step_lbl.pack(pady=(0, 10), padx=40, anchor="w")

        self.progress = ctk.CTkProgressBar(
            self.app, width=560, height=22,
            progress_color=green, fg_color="#1B2228")
        self.progress.set(0)
        self.progress.pack(pady=(4, 8))

        self.pct_lbl = ctk.CTkLabel(
            self.app, text="0%",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=neon)
        self.pct_lbl.pack()

        self.log_lbl = ctk.CTkLabel(
            self.app, text="",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color="#6B7C87", wraplength=560, justify="center")
        self.log_lbl.pack(pady=(14, 0))

    # --- потокобезопасные апдейты UI ---
    def _ui(self, fn, *a, **kw):
        try:
            self.app.after(0, lambda: fn(*a, **kw))
        except Exception:
            pass

    def set_step(self, text):
        self._ui(self.step_lbl.configure, text=text)

    def set_log(self, text):
        self._ui(self.log_lbl.configure, text=text)

    def set_progress(self, frac):
        frac = max(0.0, min(1.0, float(frac)))
        self._ui(self.progress.set, frac)
        self._ui(self.pct_lbl.configure, text=f"{int(frac * 100)}%")

    def _on_close(self):
        try:
            self.app.destroy()
        except Exception:
            pass
        os._exit(0)

    # ------------------------------------------------------------------
    # Шаги
    # ------------------------------------------------------------------
    def step_python(self):
        self.set_step("Шаг 1/4 — Проверка Python и библиотек")
        py = _python_exe()
        if py is None:
            # exe-режим: все зависимости уже вшиты в исполняемый файл
            self.set_log("Запуск из exe: зависимости уже встроены.")
            self.set_progress(0.25)
            return
        req = APP_DIR / "requirements.txt"
        if not req.exists():
            self.set_log("requirements.txt не найден — пропускаю.")
            self.set_progress(0.25)
            return
        self.set_log("Проверяю и доустанавливаю зависимости в фоне...")
        rc, out = _run([py, "-m", "pip", "install", "-r", str(req),
                        "--disable-pip-version-check"])
        if rc != 0:
            self.set_log("Часть зависимостей не установилась (продолжаю).")
        else:
            self.set_log("Зависимости готовы.")
        self.set_progress(0.25)

    def step_ollama(self):
        self.set_step("Шаг 2/4 — Проверка Ollama")
        if _find_ollama():
            self.set_log("Ollama уже установлена.")
            self.set_progress(0.5)
            return
        self.set_log("Ollama не найдена. Скачиваю официальный установщик...")
        setup = Path(os.environ.get("TEMP", ".")) / "OllamaSetup.exe"
        try:
            if requests is None:
                raise RuntimeError("нет библиотеки requests")
            r = requests.get(OLLAMA_DOWNLOAD, stream=True, timeout=60)
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            got = 0
            with open(setup, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if not chunk:
                        continue
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        # скачивание установщика — 50%..65%
                        self.set_progress(0.5 + 0.15 * got / total)
            self.set_log("Запускаю тихую установку Ollama (OllamaSetup.exe /silent)...")
            os.system(f'"{setup}" /silent')
            self.set_log("Жду появления Ollama в трее...")
            _ollama_ready(timeout=180)
        except Exception as e:
            self.set_log(f"Автоустановка Ollama не удалась: {e}")
        self.set_progress(0.65)

    def step_models(self):
        self.set_step(f"Шаг 3/4 — Скачивание модели {MODEL}")
        exe = _find_ollama()
        if not exe:
            self.set_log("Ollama недоступна — пропускаю скачивание модели.")
            self.set_progress(1.0)
            return
        # если модель уже есть — быстро проходим
        _, listing = _run([exe, "list"])
        if MODEL.split(":")[0] in listing:
            self.set_log(f"Модель {MODEL} уже установлена.")
            self.set_progress(1.0)
            return

        self.set_log("Скачиваю модель (может занять несколько минут)...")
        try:
            proc = subprocess.Popen(
                [exe, "pull", MODEL],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1)
            last = 0.65
            for line in proc.stdout:
                m = re.findall(r"(\d{1,3})%", line)
                if m:
                    p = int(m[-1]) / 100.0
                    # 65%..99%
                    frac = 0.65 + 0.34 * p
                    if frac > 0.99:
                        frac = 0.99
                    if abs(frac - last) >= 0.005:
                        last = frac
                        self.set_progress(frac)
                    self.set_log(line.strip()[:120])
            proc.wait()
        except Exception as e:
            self.set_log(f"Ошибка скачивания модели: {e}")
        self.set_progress(1.0)

    def step_launch(self):
        self.set_step("Шаг 4/4 — Запуск Кати")
        self.set_log("Всё готово! Открываю неоновый интерфейс...")
        self.set_progress(1.0)
        self.done = True
        time.sleep(1.2)
        self._launch_main()

    def _launch_main(self):
        try:
            _diag("_launch_main: start")
            self.set_log("Всё готово! Открываю неоновый интерфейс...")
            py = _python_exe()
            main = APP_DIR / "main.py"
            if getattr(sys, "frozen", False) or py is None:
                # exe-режим: интерфейс откроем в ГЛАВНОМ потоке после закрытия мастера
                _diag("_launch_main: frozen, set launch flag")
                self._should_launch = True
                self._ui(self.app.quit)
                return
            if py is not None:
                _diag("_launch_main: Popen python main.py")
                subprocess.Popen([py, str(main)], cwd=str(APP_DIR),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            _diag("_launch_main: outer fail:\n" + traceback.format_exc())
        self._ui(self.app.destroy)
        os._exit(0)

    # ------------------------------------------------------------------
    def run(self):
        def worker():
            try:
                _diag("worker: step_python")
                self.step_python()
                _diag("worker: step_ollama")
                self.step_ollama()
                _diag("worker: step_models")
                self.step_models()
                _diag("worker: step_launch")
                self.step_launch()
            except Exception:
                _diag("worker fail:\n" + traceback.format_exc())
                self.set_log("Что-то пошло не так, но я продолжаю:\n" +
                             traceback.format_exc()[:200])
                try:
                    self.step_launch()
                except Exception:
                    pass
        threading.Thread(target=worker, daemon=True).start()
        try:
            self.app.mainloop()
        except Exception:
            _diag("mainloop fail:\n" + traceback.format_exc())
        # после закрытия мастера запускаем интерфейс в ГЛАВНОМ потоке
        try:
            self.app.destroy()
        except Exception:
            pass
        if self._should_launch:
            _diag("run: launching gui in main thread")
            try:
                from gui import run as gui_run
                gui_run()
                _diag("run: gui_run returned")
            except Exception:
                _diag("run: gui_run fail:\n" + traceback.format_exc())


def main():
    try:
        if ctk is None:
            # fallback без GUI — просто запускаем приложение
            from gui import run
            run()
            return
        SetupWizard().run()
    except Exception:
        try:
            from gui import run
            run()
        except Exception:
            print("Установщик не смог запуститься:\n", traceback.format_exc())


if __name__ == "__main__":
    try:
        import multiprocessing
        multiprocessing.freeze_support()
    except Exception:
        pass
    try:
        main()
    except Exception:
        os._exit(1)
