"""
Streaming Russian speech-to-text built on Vosk.

- Downloads the compact Russian model on first use.
- Streams 16 kHz mono int16 audio from sounddevice.
- Keeps all heavy work off the Tk main thread.
- Cooperates with EchoGuard so Katya never transcribes her own voice.
"""

from __future__ import annotations

import ctypes
import json
import logging
import math
import os
import shutil
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

import requests

from config import (
    SAMPLE_RATE,
    VOSK_MODEL_DIR,
    VOSK_MODEL_NAME,
    VOSK_MODEL_URL,
    WAKE_WORDS,
)
from core.echo_guard import EchoGuard, get_echo_guard

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], None]
TextCallback = Callable[[str], None]
LevelCallback = Callable[[float], None]
ErrorCallback = Callable[[str], None]


class ModelDownloadError(RuntimeError):
    pass


def vosk_compatible_path(path: Path) -> str:
    """
    Vosk's native loader cannot open paths with non-ASCII characters on some
    Windows builds. The 8.3 short path is pure ASCII and always resolves to
    the same directory, so e.g. «Документы» works transparently.
    """
    text = str(path)
    if os.name != "nt":
        return text
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        result = ctypes.windll.kernel32.GetShortPathNameW(
            text, buffer, len(buffer)
        )
        if result and buffer.value:
            return buffer.value
    except Exception:
        logger.debug("GetShortPathNameW failed for %s", text, exc_info=True)
    return text


def download_vosk_model(
    destination: Path | None = None,
    progress: ProgressCallback | None = None,
    url: str = VOSK_MODEL_URL,
) -> Path:
    """Download and safely unpack the Russian Vosk model."""
    destination = Path(destination or VOSK_MODEL_DIR)
    if destination.exists() and any(destination.iterdir()):
        if progress:
            progress(1.0, "Модель Vosk уже установлена")
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    archive_path = destination.parent / f"{VOSK_MODEL_NAME}.zip.part"
    if progress:
        progress(0.0, "Скачивание русской модели Vosk…")

    try:
        headers = {
            "User-Agent": "Katya/2.11.0 (+https://github.com/)",
            "Accept": "application/zip,application/octet-stream,*/*",
        }
        downloaded = 0
        total = 0
        try:
            with requests.get(
                url,
                stream=True,
                timeout=(10, 90),
                headers=headers,
            ) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", "0") or 0)
                with archive_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if progress:
                            fraction = (downloaded / total) if total else 0.15
                            progress(
                                min(0.92, fraction * 0.92),
                                f"Модель Vosk: {downloaded / 1_048_576:.1f} МБ",
                            )
        except requests.RequestException:
            # Fallback for environments where requests' TLS stack is blocked.
            logger.warning("requests download failed, retrying with urllib", exc_info=True)
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=45) as response:
                total = int(response.headers.get("Content-Length", "0") or 0)
                downloaded = 0
                with archive_path.open("wb") as handle:
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if progress:
                            fraction = (downloaded / total) if total else 0.15
                            progress(
                                min(0.92, fraction * 0.92),
                                f"Модель Vosk: {downloaded / 1_048_576:.1f} МБ",
                            )

        if total and downloaded < total:
            raise ModelDownloadError(
                f"Модель скачана не полностью: {downloaded} из {total} байт"
            )

        if progress:
            progress(0.94, "Распаковка модели Vosk…")

        if not zipfile.is_zipfile(archive_path):
            raise ModelDownloadError("Скачанный файл модели повреждён (не ZIP)")

        with tempfile.TemporaryDirectory(dir=str(destination.parent)) as temp_dir:
            temp_path = Path(temp_dir)
            with zipfile.ZipFile(archive_path) as archive:
                root = temp_path.resolve()
                for member in archive.infolist():
                    target = (temp_path / member.filename).resolve()
                    if not str(target).startswith(str(root)):
                        raise ModelDownloadError("Небезопасный путь внутри архива Vosk")
                archive.extractall(temp_path)

            candidates = [item for item in temp_path.iterdir() if item.is_dir()]
            source = candidates[0] if len(candidates) == 1 else temp_path
            if not (source / "conf").exists() and not (source / "am").exists():
                nested = [item for item in temp_path.rglob("conf") if item.is_dir()]
                if nested:
                    source = nested[0].parent

            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            shutil.copytree(source, destination)

        if progress:
            progress(1.0, "Модель Vosk готова")
        return destination
    except Exception as exc:  # network / zip / disk
        logger.exception("Vosk model download failed")
        raise ModelDownloadError(str(exc)) from exc
    finally:
        archive_path.unlink(missing_ok=True)


class VoskSTT:
    """Thread-friendly continuous microphone recogniser."""

    def __init__(
        self,
        model_dir: Path = VOSK_MODEL_DIR,
        on_partial: TextCallback | None = None,
        on_final: TextCallback | None = None,
        on_level: LevelCallback | None = None,
        on_error: ErrorCallback | None = None,
        echo_guard: EchoGuard | None = None,
        input_device: int | str | None = None,
        auto_download: bool = True,
        strip_wake_word: bool = True,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_level = on_level
        self.on_error = on_error
        self.echo_guard = echo_guard or get_echo_guard()
        self.input_device = input_device
        self.auto_download = auto_download
        self.strip_wake_word = strip_wake_word

        self._model = None
        self._recognizer = None
        self._stream = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._running = False
        self._last_partial = ""
        self._last_final_at = 0.0
        self._last_error = ""

    # -- model -------------------------------------------------------------
    def ensure_model(self, progress: ProgressCallback | None = None) -> Path:
        if self.model_dir.exists() and (self.model_dir / "am").exists():
            return self.model_dir
        if not self.auto_download:
            raise FileNotFoundError(
                f"Модель Vosk не найдена: {self.model_dir}. Запустите setup_wizard.py"
            )
        return download_vosk_model(self.model_dir, progress)

    def _load_model(self, progress: ProgressCallback | None = None) -> None:
        try:
            import vosk
        except ImportError as exc:
            raise RuntimeError("Vosk не установлен: pip install vosk") from exc

        path = self.ensure_model(progress)
        vosk.SetLogLevel(-1)
        native_path = vosk_compatible_path(path)
        logger.info("Loading Vosk model from %s (native: %s)", path, native_path)
        model = vosk.Model(native_path)
        recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE)
        recognizer.SetWords(False)
        with self._lock:
            self._model = model
            self._recognizer = recognizer

    # -- lifecycle ---------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._running

    def start(self, progress: ProgressCallback | None = None) -> None:
        with self._lock:
            if self._running:
                return
            self._stop_event.clear()
            self._last_error = ""
            self._running = True

        try:
            self._load_model(progress)
        except Exception as exc:
            self._running = False
            self._last_error = str(exc)
            self._emit_error(str(exc))
            raise

        self._thread = threading.Thread(
            target=self._run_stream,
            name="KatyaSTT",
            daemon=True,
        )
        self._thread.start()

    @staticmethod
    def _candidate_inputs(sd, preferred) -> list[tuple[int | str, int]]:  # noqa: ANN001
        try:
            default_input = int(sd.default.device[0])
        except Exception:
            default_input = -1

        ranked: list[tuple[int, int]] = []
        for index, info in enumerate(sd.query_devices()):
            if int(info.get("max_input_channels", 0)) <= 0:
                continue
            name = str(info.get("name", "")).lower()
            score = 0
            if preferred is not None and str(preferred) == str(index):
                score += 1000
            if index == default_input:
                score += 200
            if any(word in name for word in ("microphone", "mic ", "микрофон", "микро")):
                score += 80
            if "mic input" in name or "microphone input" in name:
                score += 20
            if any(
                word in name
                for word in ("stereo mix", "стерео", "loopback", "what u hear")
            ):
                score -= 300
            ranked.append((score, index))

        ordered = [index for _score, index in sorted(ranked, reverse=True)]
        if preferred is not None and preferred not in ordered:
            ordered.insert(0, preferred)

        unique: list[int | str] = []
        for item in ordered:
            if item not in unique:
                unique.append(item)

        result: list[tuple[int | str, int]] = []
        for device in unique:
            try:
                info = sd.query_devices(device)
            except Exception:
                continue
            native = int(float(info.get("default_samplerate") or 48000))
            for rate in (native, 48000, 44100, 16000):
                try:
                    sd.check_input_settings(
                        device=device,
                        channels=1,
                        dtype="int16",
                        samplerate=rate,
                    )
                    result.append((device, rate))
                    break
                except Exception:
                    continue
        return result

    def _run_stream(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            self._running = False
            self._emit_error(f"sounddevice не установлен: {exc}")
            return

        stream = None
        last_error = ""
        try:
            candidates = self._candidate_inputs(sd, self.input_device)
            if not candidates:
                raise RuntimeError("Нет доступного устройства ввода (микрофон отключён?)")

            for device, capture_rate in candidates:
                def callback(  # noqa: ANN001
                    indata,
                    frames,
                    time_info,
                    status,
                    rate=capture_rate,
                ) -> None:
                    if status:
                        logger.debug("PortAudio status: %s", status)
                    self._process_audio(indata, rate)

                candidate = None
                try:
                    candidate = sd.RawInputStream(
                        samplerate=capture_rate,
                        # blocksize=0 lets WDM-KS/Windows choose a valid buffer.
                        # A fixed size triggers "Blocking API not supported".
                        blocksize=0,
                        device=device,
                        dtype="int16",
                        channels=1,
                        callback=callback,
                    )
                    candidate.start()
                    stream = candidate
                    self.input_device = device
                    logger.info(
                        "Microphone opened: %s @ %s Hz", device, capture_rate
                    )
                    break
                except Exception as exc:
                    last_error = str(exc)
                    logger.warning("Input %s @ %s failed: %s", device, capture_rate, exc)
                    if candidate is not None:
                        try:
                            candidate.close()
                        except Exception:
                            pass

            if stream is None:
                raise RuntimeError(last_error or "Не удалось открыть микрофон")
            with self._lock:
                self._stream = stream
            logger.info("Continuous listening started")
            while not self._stop_event.wait(0.2):
                pass
        except Exception as exc:
            logger.exception("Microphone stream failed")
            self._last_error = str(exc)
            self._emit_error(f"Микрофон: {exc}")
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    logger.debug("stream close failed", exc_info=True)
            with self._lock:
                self._stream = None
                self._running = False
                self._recognizer = None
            logger.info("Microphone stream stopped")

    def stop(self, timeout: float = 4.0) -> None:
        self._stop_event.set()
        stream = self._stream
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        with self._lock:
            self._running = False
            self._stream = None
        self._thread = None

    def restart(self) -> None:
        self.stop()
        time.sleep(0.15)
        self.start()

    def set_device(self, device: int | str | None) -> None:
        self.input_device = device
        if self._running:
            self.restart()

    # -- audio / recognition ----------------------------------------------
    def _process_audio(self, indata, capture_rate: int = SAMPLE_RATE) -> None:  # noqa: ANN001
        try:
            import numpy as np

            recognizer = self._recognizer
            if recognizer is None or not self._running:
                return

            samples = np.frombuffer(bytes(indata), dtype=np.int16)
            if samples.size == 0:
                return

            if self.on_level:
                rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
                normalized = min(1.0, rms / 8000.0)
                self.on_level(normalized)

            # Do not feed Katya's own output into the recogniser at all.
            if self.echo_guard.is_speaking:
                return

            audio_bytes = bytes(indata)
            if int(capture_rate) != SAMPLE_RATE:
                target_length = max(1, int(samples.size * SAMPLE_RATE / capture_rate))
                source_axis = np.arange(samples.size, dtype=np.float64)
                target_axis = np.linspace(0, samples.size - 1, target_length)
                resampled = np.interp(
                    target_axis, source_axis, samples.astype(np.float64)
                )
                audio_bytes = np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()

            if recognizer.AcceptWaveform(audio_bytes):
                payload = json.loads(recognizer.Result() or "{}")
                text = str(payload.get("text", "")).strip()
                if text:
                    self._handle_final(text)
            else:
                payload = json.loads(recognizer.PartialResult() or "{}")
                partial = str(payload.get("partial", "")).strip()
                if partial and partial != self._last_partial:
                    self._last_partial = partial
                    if not self.echo_guard.is_probable_echo(partial):
                        self._emit_partial(partial)
        except Exception:
            logger.exception("Recognition callback failed")

    def _handle_final(self, text: str) -> None:
        if len(text) < 2:
            return
        if self.echo_guard.should_ignore(text):
            logger.debug("Echo ignored: %s", text)
            return

        cleaned = self._strip_wake_word(text) if self.strip_wake_word else text
        cleaned = cleaned.strip(" ,.!?-")
        if len(cleaned) < 2:
            return
        self._last_partial = ""
        self._last_final_at = time.monotonic()
        self._emit_final(cleaned)

    @staticmethod
    def _strip_wake_word(text: str) -> str:
        lowered = text.lower().strip()
        for wake in WAKE_WORDS:
            if lowered.startswith(wake):
                return text[len(wake) :].lstrip(" ,.!?-")
        return text

    # -- callbacks ---------------------------------------------------------
    def _emit_partial(self, text: str) -> None:
        if self.on_partial:
            try:
                self.on_partial(text)
            except Exception:
                logger.exception("partial callback failed")

    def _emit_final(self, text: str) -> None:
        if self.on_final:
            try:
                self.on_final(text)
            except Exception:
                logger.exception("final callback failed")

    def _emit_error(self, text: str) -> None:
        self._last_error = text
        if self.on_error:
            try:
                self.on_error(text)
            except Exception:
                logger.exception("error callback failed")

    # -- diagnostics -------------------------------------------------------
    @staticmethod
    def list_input_devices() -> list[dict[str, object]]:
        try:
            import sounddevice as sd

            result: list[dict[str, object]] = []
            for index, device in enumerate(sd.query_devices()):
                if int(device.get("max_input_channels", 0)) > 0:
                    result.append(
                        {
                            "index": index,
                            "name": str(device.get("name", f"Input {index}")),
                            "channels": int(device.get("max_input_channels", 0)),
                            "default": index == sd.default.device[0],
                        }
                    )
            return result
        except Exception:
            logger.exception("Cannot enumerate input devices")
            return []

    def status(self) -> dict[str, object]:
        return {
            "running": self._running,
            "model": str(self.model_dir),
            "device": self.input_device,
            "last_error": self._last_error,
            "last_final_at": self._last_final_at,
        }


def mic_level_to_dbfs(level: float) -> float:
    """Convert the 0..1 UI level to approximate dBFS for the HUD."""
    level = max(1e-5, min(1.0, float(level)))
    return 20.0 * math.log10(level)
