"""
Протокол Cyber-Coach — Roblox real-time vision coach.

Design goals:
  * capture only the foreground Roblox window, never the whole desktop;
  * use mss + Pillow, downscale before JPEG encoding (low CPU / no game lag);
  * send one frame every N seconds to llava through Ollama;
  * speak one short, aggressive combo tip, deduplicate repeats;
  * all work in an asyncio task owned by the app runtime.
"""

from __future__ import annotations

import asyncio
import base64
import ctypes
import io
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

import psutil
from PIL import Image

import config
from config import (
    COACH_INTERVAL_SECONDS,
    COACH_MIN_GAP_SECONDS,
    COACH_PROMPT,
    CACHE_DIR,
    ROBLOX_PROCESS_NAMES,
    ROBLOX_TITLE_HINTS,
)
from core.brain import Brain, BrainError
from core.echo_guard import get_echo_guard

logger = logging.getLogger(__name__)

SpeakCallback = Callable[[str], Awaitable[None]]
StatusCallback = Callable[[str], None]
FrameCallback = Callable[[Path], None]

_IS_WINDOWS = os.name == "nt"
_user32 = ctypes.windll.user32 if _IS_WINDOWS else None


@dataclass(slots=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    process: str
    rect: tuple[int, int, int, int]
    minimized: bool = False
    visible: bool = True

    @property
    def width(self) -> int:
        return max(0, self.rect[2] - self.rect[0])

    @property
    def height(self) -> int:
        return max(0, self.rect[3] - self.rect[1])

    @property
    def is_roblox(self) -> bool:
        process = self.process.lower()
        title = self.title.lower()
        return process in ROBLOX_PROCESS_NAMES or any(
            hint in title for hint in ROBLOX_TITLE_HINTS
        )


@dataclass(slots=True)
class CoachStatus:
    running: bool = False
    analyzing: bool = False
    last_advice: str = ""
    last_analysis_at: float = 0.0
    last_error: str = ""
    frames_sent: int = 0
    advice_count: int = 0
    active_window: str = ""


@dataclass(slots=True)
class _Frame:
    base64_jpeg: str
    preview_path: Path
    width: int
    height: int
    captured_at: float = field(default_factory=time.monotonic)


class CyberCoach:
    """Async Roblox vision coach with strict foreground-only capture."""

    def __init__(
        self,
        brain: Brain,
        speak: SpeakCallback,
        on_status: StatusCallback | None = None,
        on_frame: FrameCallback | None = None,
        interval: float = COACH_INTERVAL_SECONDS,
        min_gap: float = COACH_MIN_GAP_SECONDS,
        vision_provider: str = "local",
    ) -> None:
        self.brain = brain
        self.speak = speak
        self.on_status = on_status
        self.on_frame = on_frame
        self.interval = max(1.0, float(interval))
        self.min_gap = max(self.interval, float(min_gap))
        self.vision_provider = vision_provider

        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._capture_only_when_roblox = True
        self._last_advice_at = 0.0
        self._recent_advice: list[str] = []
        self._status = CoachStatus()
        self._consecutive_errors = 0
        self._last_frame: _Frame | None = None

    # -- properties / settings --------------------------------------------
    @property
    def running(self) -> bool:
        return self._running

    @property
    def status(self) -> CoachStatus:
        return self._status

    @property
    def last_frame(self) -> _Frame | None:
        return self._last_frame

    def set_privacy_mode(self, capture_only_when_roblox: bool) -> None:
        self._capture_only_when_roblox = bool(capture_only_when_roblox)

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        if self._running:
            return
        settings = config.load_settings()
        self._capture_only_when_roblox = bool(
            settings.get("privacy", {}).get(
                "capture_only_when_roblox_focused", True
            )
        )
        self._running = True
        self._status.running = True
        self._status.last_error = ""
        self._consecutive_errors = 0
        self._task = asyncio.create_task(self._run(), name="KatyaCyberCoach")
        self._emit_status("Cyber-Coach: онлайн")

    async def stop(self) -> None:
        self._running = False
        task = self._task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._status.running = False
        self._status.analyzing = False
        self._emit_status("Cyber-Coach: выключен")

    async def toggle(self) -> bool:
        if self._running:
            await self.stop()
        else:
            await self.start()
        return self._running

    # -- capture -----------------------------------------------------------
    @staticmethod
    def active_window() -> WindowInfo | None:
        if not _IS_WINDOWS:
            return None
        hwnd = int(_user32.GetForegroundWindow())
        if not hwnd:
            return None

        length = int(_user32.GetWindowTextLengthW(hwnd))
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value

        pid = ctypes.c_ulong()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        try:
            process = psutil.Process(int(pid.value)).name()
        except (psutil.Error, ValueError):
            process = "unknown"

        from ctypes import wintypes

        rect = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(rect))
        minimized = bool(_user32.IsIconic(hwnd))
        visible = bool(_user32.IsWindowVisible(hwnd))
        return WindowInfo(
            hwnd=hwnd,
            title=title,
            pid=int(pid.value),
            process=process,
            rect=(int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
            minimized=minimized,
            visible=visible,
        )

    def capture_roblox_frame(
        self,
        max_width: int = 960,
        quality: int = 68,
        save_preview: bool = True,
    ) -> _Frame | None:
        """Fast foreground-only grab. Returns None when Roblox is not focused."""
        window = self.active_window()
        if window is None:
            return None
        self._status.active_window = f"{window.process} — {window.title[:70]}"

        if self._capture_only_when_roblox and not window.is_roblox:
            return None
        if window.minimized or not window.visible:
            return None
        if window.width < 240 or window.height < 160:
            return None
        if not _IS_WINDOWS:
            return None

        # The taskbar / window borders can push the rect off-screen.
        try:
            import mss

            # mss keeps a GDI device context; create it inside the calling
            # thread instead of sharing it across asyncio's thread pool.
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                left = max(int(monitor["left"]), window.rect[0])
                top = max(int(monitor["top"]), window.rect[1])
                right = min(int(monitor["left"] + monitor["width"]), window.rect[2])
                bottom = min(int(monitor["top"] + monitor["height"]), window.rect[3])
                if right - left < 240 or bottom - top < 160:
                    return None

                shot = sct.grab(
                    {
                        "left": left,
                        "top": top,
                        "width": right - left,
                        "height": bottom - top,
                    }
                )
                image = Image.frombytes("RGB", shot.size, shot.rgb)
        except Exception as exc:
            logger.warning("Frame capture failed: %s", exc)
            self._status.last_error = f"Захват: {exc}"
            return None

        if image.width > max_width:
            ratio = max_width / float(image.width)
            image = image.resize(
                (max_width, max(1, int(image.height * ratio))),
                Image.Resampling.BILINEAR,
            )

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=False)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

        preview_path = CACHE_DIR / "coach_last_frame.jpg"
        if save_preview:
            try:
                preview_path.write_bytes(buffer.getvalue())
            except OSError:
                logger.debug("Cannot write coach preview", exc_info=True)

        frame = _Frame(
            base64_jpeg=encoded,
            preview_path=preview_path,
            width=image.width,
            height=image.height,
        )
        self._last_frame = frame
        if self.on_frame and save_preview:
            try:
                self.on_frame(preview_path)
            except Exception:
                logger.debug("frame callback failed", exc_info=True)
        return frame

    # -- analysis ----------------------------------------------------------
    def _clean_advice(self, raw: str) -> str:
        text = " ".join((raw or "").replace("\n", " ").split())
        for prefix in ("Совет:", "Совет —", "Катя:", "Coach:"):
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix) :].strip()
        if len(text) > 220:
            cut = text[:220]
            text = cut.rsplit(" ", 1)[0] + "…"
        return text.strip(" \"'«»")

    def _is_duplicate(self, advice: str) -> bool:
        normalized = " ".join(advice.lower().replace("ё", "е").split())
        for previous in self._recent_advice[-4:]:
            if normalized == previous:
                return True
            first = set(normalized.split())
            second = set(previous.split())
            if first and second:
                union = first | second
                if union and len(first & second) / len(union) > 0.8:
                    return True
        return False

    async def analyze_once(self, force: bool = False) -> str | None:
        if self._status.analyzing:
            return None
        if not force and time.monotonic() - self._last_advice_at < self.min_gap:
            return None

        frame = await asyncio.to_thread(self.capture_roblox_frame)
        if frame is None:
            return None

        self._status.analyzing = True
        self._emit_status("Cyber-Coach: анализ кадра…")
        try:
            response = await self.brain.chat(
                "Разбери текущий бой на кадре и дай один совет по комбо.",
                images=[frame.base64_jpeg],
                remember=False,
                system_prompt=COACH_PROMPT,
                temperature=0.85,
                max_tokens=90,
                provider=self.vision_provider,
            )
            advice = self._clean_advice(response.text)
            self._status.frames_sent += 1
            self._status.last_analysis_at = time.time()
            if not advice:
                return None

            if self._is_duplicate(advice):
                self._emit_status("Cyber-Coach: повтор совета отфильтрован")
                return None

            self._recent_advice.append(
                " ".join(advice.lower().replace("ё", "е").split())
            )
            self._recent_advice = self._recent_advice[-12:]
            self._last_advice_at = time.monotonic()
            self._status.last_advice = advice
            self._status.advice_count += 1
            self._status.last_error = ""
            self._status.analyzing = False
            self._emit_status(f"Cyber-Coach: {advice}")

            if not get_echo_guard().is_speaking:
                try:
                    await self.speak(advice)
                except Exception:
                    logger.exception("Coach speak callback failed")
            return advice
        except BrainError as exc:
            self._consecutive_errors += 1
            self._status.last_error = str(exc)
            self._emit_status(f"Cyber-Coach: {exc}")
            if self._consecutive_errors >= 3:
                await asyncio.sleep(min(30.0, 3.0 * self._consecutive_errors))
            return None
        except Exception as exc:
            self._consecutive_errors += 1
            logger.exception("Coach analysis failed")
            self._status.last_error = str(exc)
            return None
        finally:
            self._status.analyzing = False

    async def _run(self) -> None:
        logger.info("Cyber-Coach loop started")
        try:
            while self._running:
                started = time.monotonic()
                try:
                    if self._capture_only_when_roblox:
                        window = await asyncio.to_thread(self.active_window)
                        if window is None or not window.is_roblox:
                            self._emit_status("Cyber-Coach: Roblox не в фокусе — пауза")
                            await asyncio.sleep(1.5)
                            continue
                    await self.analyze_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Cyber-Coach loop iteration failed")

                elapsed = time.monotonic() - started
                await asyncio.sleep(max(0.35, self.interval - elapsed))
        except asyncio.CancelledError:
            logger.info("Cyber-Coach loop cancelled")
            raise
        finally:
            self._running = False
            self._status.running = False
            self._status.analyzing = False

    # -- callbacks ---------------------------------------------------------
    def _emit_status(self, text: str) -> None:
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:
                logger.debug("coach status callback failed", exc_info=True)
