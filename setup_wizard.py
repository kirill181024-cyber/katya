"""
Katya 2.11.0 — Hardware-Adaptive AI setup wizard.

Scans RAM/CPU/GPU with psutil, chooses qwen2.5:7b on 16 GB+ systems or
gemma3:4b on lighter machines, silently installs Ollama, pulls the selected
model (+ llava for Cyber-Coach), downloads the Russian Vosk model and shows
honest progress. All work happens in a worker thread.
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import customtkinter as ctk
import psutil

import config

try:
    import requests
except ImportError:  # wizard can still download via urllib
    requests = None  # type: ignore[assignment]

COLORS = {
    "bg": "#03060A",
    "panel": "#071018",
    "panel2": "#0A1620",
    "neon": "#00F0FF",
    "neon_dim": "#0A4E58",
    "text": "#D9F8FF",
    "muted": "#6F9099",
    "ok": "#31FFB4",
    "warn": "#FFB020",
    "error": "#FF3B6B",
    "line": "#123440",
}

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_API = config.OLLAMA_TAGS_URL
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)


def total_ram_gb() -> float:
    return psutil.virtual_memory().total / (1024**3)


def choose_model() -> tuple[str, str]:
    ram = total_ram_gb()
    if ram >= 16.0:
        return config.MODEL_FAST, f"{ram:.1f} ГБ RAM → {config.MODEL_FAST} (полный мозг)"
    return config.MODEL_LIGHT, f"{ram:.1f} ГБ RAM → {config.MODEL_LIGHT} (лёгкий мозг)"


def gpu_summary() -> str:
    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        try:
            result = subprocess.run(
                [
                    nvidia,
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=CREATE_NO_WINDOW,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().splitlines()[0]
        except Exception:
            pass
    try:
        command = (
            "Get-CimInstance Win32_VideoController | "
            "Select-Object -First 1 -ExpandProperty Name"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        if result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return "GPU не определён"


def find_ollama() -> Path | None:
    candidate = shutil.which("ollama")
    paths = []
    if candidate:
        paths.append(Path(candidate))
    local = os.getenv("LOCALAPPDATA")
    if local:
        paths.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
    program_files = os.getenv("ProgramFiles")
    if program_files:
        paths.append(Path(program_files) / "Ollama" / "ollama.exe")
    for path in paths:
        if path.exists():
            return path
    return None


def ollama_online(timeout: float = 2.0) -> bool:
    try:
        if requests:
            response = requests.get(OLLAMA_API, timeout=timeout)
            return response.status_code == 200
        with urlopen(OLLAMA_API, timeout=timeout) as response:  # noqa: S310
            return int(response.status) == 200
    except Exception:
        return False


class SetupWizard(ctk.CTk):
    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        super().__init__()
        self.title(f"КАТЯ {config.APP_VERSION} // HARDWARE-ADAPTIVE AI SETUP")
        self.geometry("940x700")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["bg"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._running = False
        self._closed = False
        self._model, self._model_reason = choose_model()
        self._ollama_path: Path | None = find_ollama()

        self._build()
        self.after(80, self._poll)
        self._detect_hardware()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=28, pady=(24, 8))
        ctk.CTkLabel(
            header,
            text="КАТЯ 2.11.0",
            font=ctk.CTkFont("Segoe UI", 30, "bold"),
            text_color=COLORS["neon"],
        ).pack(side="left")
        ctk.CTkLabel(
            header,
            text="  HARDWARE-ADAPTIVE AI",
            font=ctk.CTkFont("Consolas", 11, "bold"),
            text_color=COLORS["muted"],
        ).pack(side="left", pady=(12, 0))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=28, pady=8)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        hardware = ctk.CTkFrame(
            body,
            fg_color=COLORS["panel"],
            corner_radius=14,
            border_width=1,
            border_color=COLORS["line"],
        )
        hardware.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        hardware.grid_columnconfigure(1, weight=1)
        self.hardware_labels: dict[str, ctk.CTkLabel] = {}
        for index, (key, title) in enumerate(
            (
                ("cpu", "CPU"),
                ("ram", "RAM"),
                ("gpu", "GPU"),
                ("model", "ВЫБРАННАЯ МОДЕЛЬ"),
            )
        ):
            ctk.CTkLabel(
                hardware,
                text=title,
                font=ctk.CTkFont("Consolas", 9, "bold"),
                text_color=COLORS["muted"],
                anchor="w",
                width=140,
            ).grid(row=index, column=0, sticky="w", padx=16, pady=4)
            value = ctk.CTkLabel(
                hardware,
                text="сканирование…",
                font=ctk.CTkFont("Consolas", 10),
                text_color=COLORS["text"],
                anchor="w",
            )
            value.grid(row=index, column=1, sticky="ew", padx=16, pady=4)
            self.hardware_labels[key] = value
        hardware.grid_rowconfigure(4, minsize=8)

        options = ctk.CTkFrame(
            body,
            fg_color=COLORS["panel"],
            corner_radius=14,
            border_width=1,
            border_color=COLORS["line"],
        )
        options.grid(row=1, column=0, sticky="nsew")
        options.grid_columnconfigure(0, weight=1)
        options.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(
            options,
            text="ПЛАН УСТАНОВКИ",
            font=ctk.CTkFont("Consolas", 11, "bold"),
            text_color=COLORS["neon"],
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))

        self.vision_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options,
            text=f"Установить {config.MODEL_VISION} для Roblox Cyber-Coach (анализ экрана)",
            variable=self.vision_var,
            font=ctk.CTkFont("Consolas", 9),
            text_color=COLORS["text"],
            fg_color=COLORS["neon_dim"],
            hover_color=COLORS["neon_dim"],
            checkmark_color=COLORS["bg"],
            border_color=COLORS["neon_dim"],
        ).grid(row=1, column=0, sticky="w", padx=16, pady=4)

        self.vosk_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options,
            text="Скачать русскую модель Vosk (постоянное прослушивание, ~45 МБ)",
            variable=self.vosk_var,
            font=ctk.CTkFont("Consolas", 9),
            text_color=COLORS["text"],
            fg_color=COLORS["neon_dim"],
            hover_color=COLORS["neon_dim"],
            checkmark_color=COLORS["bg"],
            border_color=COLORS["neon_dim"],
        ).grid(row=2, column=0, sticky="w", padx=16, pady=4)

        self.progress = ctk.CTkProgressBar(
            options,
            height=10,
            corner_radius=5,
            fg_color=COLORS["panel2"],
            progress_color=COLORS["neon"],
        )
        self.progress.set(0)
        self.progress.grid(row=3, column=0, sticky="ew", padx=16, pady=(14, 4))

        self.status_label = ctk.CTkLabel(
            options,
            text="Готов к установке.",
            font=ctk.CTkFont("Consolas", 10),
            text_color=COLORS["neon"],
            anchor="w",
        )
        self.status_label.grid(row=4, column=0, sticky="new", padx=16, pady=(4, 4))

        self.log_box = ctk.CTkTextbox(
            options,
            height=150,
            fg_color=COLORS["panel2"],
            border_width=0,
            text_color=COLORS["muted"],
            font=ctk.CTkFont("Consolas", 9),
            corner_radius=8,
            wrap="word",
        )
        self.log_box.grid(row=5, column=0, sticky="nsew", padx=16, pady=(4, 10))
        self.log_box.configure(state="disabled")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=28, pady=(8, 24))
        self.install_button = ctk.CTkButton(
            buttons,
            text="УСТАНОВИТЬ ВСЁ",
            height=44,
            width=240,
            corner_radius=10,
            fg_color=COLORS["neon_dim"],
            hover_color="#0E7C8C",
            text_color=COLORS["text"],
            font=ctk.CTkFont("Segoe UI", 14, "bold"),
            command=self._start_install,
        )
        self.install_button.pack(side="left")
        self.skip_button = ctk.CTkButton(
            buttons,
            text="ПРОПУСТИТЬ",
            height=44,
            width=140,
            corner_radius=10,
            fg_color=COLORS["panel2"],
            hover_color=COLORS["panel"],
            text_color=COLORS["muted"],
            font=ctk.CTkFont("Consolas", 10, "bold"),
            command=self._on_close,
        )
        self.skip_button.pack(side="right")

    # ------------------------------------------------------------------
    def _detect_hardware(self) -> None:
        cpu = psutil.cpu_count(logical=True) or 0
        physical = psutil.cpu_count(logical=False) or cpu
        self.hardware_labels["cpu"].configure(
            text=f"{physical} ядер / {cpu} потоков · {psutil.cpu_percent(interval=0.15):.0f}%"
        )
        self.hardware_labels["ram"].configure(
            text=f"{total_ram_gb():.1f} ГБ · {self._model_reason}"
        )
        self.hardware_labels["gpu"].configure(text=gpu_summary())
        self.hardware_labels["model"].configure(
            text=f"{self._model}  //  {'Ollama найден' if self._ollama_path else 'Ollama будет установлен'}",
            text_color=COLORS["neon"],
        )
        self._log(f"Выбрана модель: {self._model} ({self._model_reason})")
        if self._ollama_path:
            self._log(f"Ollama: {self._ollama_path}")

    # ------------------------------------------------------------------
    def _start_install(self) -> None:
        if self._running:
            return
        self._running = True
        self.install_button.configure(state="disabled", text="УСТАНОВКА…")
        self.skip_button.configure(state="disabled")
        self._worker = threading.Thread(
            target=self._install_worker,
            name="KatyaSetupWorker",
            daemon=True,
        )
        self._worker.start()

    def _install_worker(self) -> None:
        try:
            self._step("Проверка Python-зависимостей…", 0.02)
            missing = self._missing_dependencies()
            if missing:
                self._log(
                    "Не найдены пакеты: "
                    + ", ".join(missing)
                    + ". Установите requirements.txt и запустите мастер снова."
                )
                self._emit("error", "Сначала установите зависимости: pip install -r requirements.txt")
                return

            self._step("Подготовка Ollama…", 0.06)
            ollama = self._ensure_ollama()

            self._step("Запуск локального сервера Ollama…", 0.16)
            self._ensure_server(ollama)

            self._step(f"Загрузка модели {self._model}…", 0.22)
            self._pull_model(ollama, self._model, 0.22, 0.58)

            if self.vision_var.get():
                self._step(f"Загрузка vision-модели {config.MODEL_VISION}…", 0.60)
                self._pull_model(ollama, config.MODEL_VISION, 0.60, 0.84)

            if self.vosk_var.get():
                self._step("Загрузка русской модели Vosk…", 0.86)
                self._download_vosk()

            self._step("Финализация…", 0.98)
            config.update_settings(version=config.APP_VERSION)
            time.sleep(0.4)
            self._step("Готово. Катя 2.11.0 собрана и вооружена.", 1.0)
            self._emit("done", "Установка завершена")
        except Exception as exc:
            self._log(f"ОШИБКА: {exc}")
            self._emit("error", str(exc))
        finally:
            self._running = False

    @staticmethod
    def _missing_dependencies() -> list[str]:
        required = {
            "customtkinter": "customtkinter",
            "psutil": "psutil",
            "PIL": "Pillow",
            "requests": "requests",
            "sounddevice": "sounddevice",
        }
        missing = []
        for module, package in required.items():
            try:
                __import__(module)
            except Exception:
                missing.append(package)
        return missing

    def _ensure_ollama(self) -> Path:
        if self._ollama_path:
            return self._ollama_path
        installer = config.CACHE_DIR / "OllamaSetup.exe"
        if not installer.exists() or installer.stat().st_size < 1_000_000:
            self._log("Скачивание OllamaSetup.exe…")
            self._download(OLLAMA_DOWNLOAD_URL, installer, 0.06, 0.13)
        else:
            self._log("OllamaSetup.exe уже в кэше.")

        self._step("Тихая установка Ollama…", 0.13)
        attempts = [
            [str(installer), "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"],
            [str(installer), "/S"],
        ]
        last_error = ""
        for args in attempts:
            try:
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    creationflags=CREATE_NO_WINDOW,
                    check=False,
                )
                if result.returncode == 0:
                    break
                last_error = (result.stderr or result.stdout or "").strip()
            except Exception as exc:
                last_error = str(exc)
        time.sleep(2.0)
        found = find_ollama()
        if not found:
            raise RuntimeError(
                "Ollama не установилась автоматически. "
                f"Скачайте вручную: {OLLAMA_DOWNLOAD_URL}. {last_error}"
            )
        self._ollama_path = found
        self._log(f"Ollama установлена: {found}")
        return found

    def _ensure_server(self, ollama: Path) -> None:
        if ollama_online():
            self._log("Ollama уже слушает localhost:11434.")
            return
        self._log("Запуск ollama serve…")
        flags = CREATE_NO_WINDOW | DETACHED_PROCESS
        subprocess.Popen(
            [str(ollama), "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        for _ in range(45):
            if ollama_online():
                self._log("Ollama server онлайн.")
                return
            time.sleep(1.0)
        raise RuntimeError(
            "Ollama не подняла порт 11434 за 45 секунд. Запустите `ollama serve` вручную."
        )

    def _pull_model(
        self,
        ollama: Path,
        model: str,
        start: float,
        end: float,
    ) -> None:
        self._log(f"ollama pull {model}")
        process = subprocess.Popen(
            [str(ollama), "pull", model],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            bufsize=1,
        )
        assert process.stdout is not None
        last_emit = 0.0
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            self._log(line)
            match = re.search(r"(\d{1,3})%", line)
            if match:
                fraction = min(100, int(match.group(1))) / 100.0
                self._step(
                    f"{model}: {match.group(1)}%",
                    start + (end - start) * fraction,
                )
            else:
                now = time.monotonic()
                if now - last_emit > 3.0:
                    self._step(f"{model}: {line[:100]}", start + (end - start) * 0.35)
                    last_emit = now
        code = process.wait()
        if code != 0:
            raise RuntimeError(f"ollama pull {model} завершился с кодом {code}")
        self._step(f"{model} готова.", end)

    def _download_vosk(self) -> None:
        from core.stt import download_vosk_model

        def progress(value: float, message: str) -> None:
            self._step(message, 0.86 + 0.11 * min(1.0, max(0.0, value)))

        download_vosk_model(progress=progress)
        self._log("Русская модель Vosk распакована.")

    # ------------------------------------------------------------------
    def _download(self, url: str, destination: Path, start: float, end: float) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_suffix(".part")
        headers = {"User-Agent": "Katya-Setup/2.11.0"}
        total = 0
        downloaded = 0

        if requests is not None:
            with requests.get(
                url,
                stream=True,
                timeout=(10, 120),
                headers=headers,
            ) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", "0") or 0)
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=512 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded += len(chunk)
                        fraction = downloaded / total if total else 0.0
                        self._step(
                            f"Скачано {downloaded / 1_048_576:.1f} МБ",
                            start + (end - start) * min(1.0, fraction),
                        )
        else:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=60) as response:  # noqa: S310
                total = int(response.headers.get("Content-Length", "0") or 0)
                with temp.open("wb") as handle:
                    while True:
                        chunk = response.read(512 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        fraction = downloaded / total if total else 0.0
                        self._step(
                            f"Скачано {downloaded / 1_048_576:.1f} МБ",
                            start + (end - start) * min(1.0, fraction),
                        )
        if total and downloaded < total:
            raise RuntimeError(
                f"Файл скачан не полностью: {downloaded} из {total} байт"
            )
        os.replace(temp, destination)
        self._log(f"Скачано: {destination.name}")

    # ------------------------------------------------------------------
    def _step(self, text: str, value: float) -> None:
        self._emit("progress", (text, value))

    def _log(self, text: str) -> None:
        self._emit("log", text)

    def _emit(self, kind: str, payload: Any) -> None:
        if not self._closed:
            self._events.put((kind, payload))

    def _poll(self) -> None:
        if self._closed:
            return
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", f"{payload}\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "progress":
                    text, value = payload
                    self.status_label.configure(text=text)
                    self.progress.set(max(0.0, min(1.0, float(value))))
                elif kind == "error":
                    self.status_label.configure(
                        text=f"Ошибка: {payload}",
                        text_color=COLORS["error"],
                    )
                    self.install_button.configure(state="normal", text="ПОВТОРИТЬ")
                    self.skip_button.configure(state="normal")
                elif kind == "done":
                    self.status_label.configure(
                        text="ГОТОВО // Катя 2.11.0 установлена",
                        text_color=COLORS["ok"],
                    )
                    self.progress.set(1.0)
                    self.install_button.configure(
                        state="normal",
                        text="ЗАПУСТИТЬ КАТЮ",
                        command=self._launch_katya,
                    )
                    self.skip_button.configure(text="ЗАКРЫТЬ", state="normal")
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _launch_katya(self) -> None:
        self._on_close()
        try:
            subprocess.Popen(
                [sys.executable, str(Path(__file__).with_name("main.py"))],
                cwd=str(config.ROOT_DIR),
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:
            print(f"Cannot launch Katya: {exc}", file=sys.stderr)

    def _on_close(self) -> None:
        self._closed = True
        try:
            self.destroy()
        except Exception:
            pass


def main() -> int:
    config.ensure_runtime_dirs()
    app = SetupWizard()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
