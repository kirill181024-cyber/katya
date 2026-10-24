"""
Neural text-to-speech for Katya.

Primary engine: edge-tts, voice ru-RU-DmitryNeural.
Playback: sounddevice + soundfile, with ffplay and Windows SAPI fallbacks.
The EchoGuard is opened for the whole playback lifetime.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from config import CACHE_DIR, TTS_RATE, TTS_VOICE, TTS_VOLUME
from core.echo_guard import EchoGuard, get_echo_guard

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str], None]

_MARKDOWN_RE = re.compile(r"[*_`#>\[\]{}]|```.*?```", re.DOTALL)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]+",
    re.UNICODE,
)


def sanitize_for_speech(text: str, limit: int = 900) -> str:
    """Make LLM output safe and pleasant to listen to."""
    text = _MARKDOWN_RE.sub(" ", text or "")
    text = _URL_RE.sub(" ссылка ", text)
    text = _EMOJI_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for separator in (". ", "! ", "? ", "; ", ", "):
        index = cut.rfind(separator)
        if index > limit * 0.55:
            return cut[: index + 1].strip()
    return cut.rsplit(" ", 1)[0] + "…"


class TextToSpeech:
    def __init__(
        self,
        voice: str = TTS_VOICE,
        rate: str = TTS_RATE,
        volume: str = TTS_VOLUME,
        echo_guard: EchoGuard | None = None,
        output_device: int | str | None = None,
        on_status: StatusCallback | None = None,
    ) -> None:
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.echo_guard = echo_guard or get_echo_guard()
        self.output_device = output_device
        self.on_status = on_status
        self._cancelled = threading.Event()
        self._speak_lock = asyncio.Lock()
        self._temp_files: list[Path] = []
        self._last_error = ""
        self._speaking = False

    # -- public ------------------------------------------------------------
    @property
    def speaking(self) -> bool:
        return self._speaking

    async def speak(self, text: str) -> bool:
        """Synthesize and play `text`. Returns False on failure."""
        clean = sanitize_for_speech(text)
        if not clean:
            return False

        async with self._speak_lock:
            self._cancelled.clear()
            self._speaking = True
            self.echo_guard.begin_speech(clean)
            audio_path: Path | None = None
            try:
                self._status("Синтез голоса…")
                audio_path = await self._synthesize(clean)
                if self._cancelled.is_set():
                    return False
                self._status("Говорю…")
                await asyncio.to_thread(self._play_file, audio_path)
                return True
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("edge-tts failed, trying SAPI")
                self._status("Edge TTS недоступен, резервный голос Windows…")
                try:
                    await asyncio.to_thread(self._speak_sapi, clean)
                    return True
                except Exception as fallback_exc:
                    self._last_error = f"{exc} / SAPI: {fallback_exc}"
                    logger.exception("SAPI fallback failed")
                    self._status("Голосовой движок недоступен")
                    return False
            finally:
                if audio_path is not None:
                    audio_path.unlink(missing_ok=True)
                self._speaking = False
                self.echo_guard.end_speech()
                self._status("Голосовой канал свободен")

    async def _synthesize(self, text: str) -> Path:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError("edge-tts не установлен") from exc

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix="katya_", suffix=".mp3", dir=str(CACHE_DIR))
        os.close(handle)
        path = Path(name)
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
        )
        await communicate.save(str(path))
        if not path.exists() or path.stat().st_size < 512:
            raise RuntimeError("edge-tts вернул пустой аудиофайл")
        self._temp_files.append(path)
        return path

    def interrupt(self) -> None:
        self._cancelled.set()
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass

    # -- playback ----------------------------------------------------------
    def _play_file(self, path: Path) -> None:
        if self._cancelled.is_set():
            return
        try:
            import sounddevice as sd
            import soundfile as sf

            data, samplerate = sf.read(str(path), dtype="float32", always_2d=True)
            if self._cancelled.is_set():
                return
            sd.play(data, samplerate=samplerate, device=self.output_device)
            sd.wait()
            return
        except Exception:
            logger.warning("soundfile playback failed", exc_info=True)

        ffplay = shutil.which("ffplay")
        if ffplay:
            process = subprocess.Popen(
                [
                    ffplay,
                    "-nodisp",
                    "-autoexit",
                    "-loglevel",
                    "quiet",
                    str(path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            while process.poll() is None:
                if self._cancelled.is_set():
                    process.terminate()
                    break
                time.sleep(0.05)
            return

        raise RuntimeError("Нет аудиодвижка для MP3: установите soundfile или ffmpeg")

    @staticmethod
    def _speak_sapi(text: str) -> None:
        """Offline Windows fallback, safe from shell-injection."""
        if os.name != "nt":
            raise RuntimeError("SAPI доступен только в Windows")
        script = (
            "$ErrorActionPreference='Stop';"
            "Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$s.Rate=2;"
            "$s.Volume=100;"
            "try{$s.SelectVoice('Microsoft Irina Desktop')}catch{};"
            "$s.Speak($env:KATYA_SAPI_TEXT);"
        )
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        env = os.environ.copy()
        env["KATYA_SAPI_TEXT"] = text
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            check=True,
            timeout=90,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    # -- helpers -----------------------------------------------------------
    def _status(self, text: str) -> None:
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:
                logger.debug("TTS status callback failed", exc_info=True)

    async def list_voices(self) -> list[str]:
        try:
            import edge_tts

            voices = await edge_tts.list_voices()
            return [
                str(item.get("ShortName", ""))
                for item in voices
                if str(item.get("Locale", "")).startswith("ru-")
            ]
        except Exception:
            logger.exception("Cannot list edge voices")
            return []

    def status(self) -> dict[str, object]:
        return {
            "voice": self.voice,
            "speaking": self._speaking,
            "last_error": self._last_error,
        }
