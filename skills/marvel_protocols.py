"""
Marvel Protocols — reversible Windows performance and privacy actions.

«Максимальный Overclock»
    * high-performance Windows power plan;
    * HIGH_PRIORITY_CLASS for the Roblox process;
    * previous power scheme and priority are restored on exit.

«Спрячь палево» (Boss Key)
    * Ctrl+Shift+H hides Roblox/browser/foreground windows;
    * mutes every audio session through pycaw;
    * restores volumes and windows on the second press.

No persistence, no stealth auto-start, no disabled security features.
Everything this module changes is tracked and reversible.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any

import psutil

from config import load_settings

logger = logging.getLogger(__name__)

_IS_WINDOWS = os.name == "nt"
_user32 = ctypes.windll.user32 if _IS_WINDOWS else None
_SW_HIDE = 0
_SW_SHOW = 5
_SW_RESTORE = 9

_HIGH_PERFORMANCE_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
_BROWSER_PROCESSES = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "opera.exe",
    "brave.exe",
    "yandex.exe",
    "vivaldi.exe",
}
_ROBLOX_PROCESSES = {
    "robloxplayerbeta.exe",
    "robloxplayerlauncher.exe",
    "robloxplayer.exe",
}


@dataclass(slots=True)
class ProtocolStatus:
    overclock: bool = False
    boss_mode: bool = False
    power_plan_changed: bool = False
    boosted_processes: int = 0
    hidden_windows: int = 0
    muted_sessions: int = 0
    last_error: str = ""


@dataclass(slots=True)
class _PowerState:
    previous_guid: str = ""
    changed: bool = False


@dataclass(slots=True)
class _PriorityState:
    pid: int
    previous_priority: int


@dataclass(slots=True)
class _WindowState:
    hwnd: int
    pid: int
    process: str
    title: str


@dataclass(slots=True)
class _AudioState:
    session_id: str
    volume: float
    muted: bool


def _run_hidden(args: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )


class OverclockProtocol:
    """Reversible FPS-oriented priority and power-plan boost."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._power = _PowerState()
        self._priorities: list[_PriorityState] = []
        self._active = False
        self._status = ProtocolStatus()

    @property
    def active(self) -> bool:
        return self._active

    @property
    def status(self) -> ProtocolStatus:
        return self._status

    def _active_power_scheme(self) -> str:
        try:
            result = _run_hidden(["powercfg", "/getactivescheme"])
            match = re.search(
                r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
                result.stdout or "",
            )
            return match.group(1) if match else ""
        except Exception:
            logger.debug("Cannot read power scheme", exc_info=True)
            return ""

    def _roblox_processes(self) -> list[psutil.Process]:
        found: list[psutil.Process] = []
        for process in psutil.process_iter(["pid", "name"]):
            try:
                name = (process.info.get("name") or "").lower()
                if name in _ROBLOX_PROCESSES:
                    found.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return found

    def engage(self, boost_power_plan: bool = True) -> dict[str, Any]:
        if not _IS_WINDOWS:
            raise RuntimeError("Overclock Protocol доступен только в Windows")
        with self._lock:
            if self._active:
                return self.report()

            self._status = ProtocolStatus(overclock=True)
            if boost_power_plan:
                previous = self._active_power_scheme()
                if previous:
                    self._power.previous_guid = previous
                    try:
                        result = _run_hidden(
                            ["powercfg", "/setactive", _HIGH_PERFORMANCE_GUID]
                        )
                        if result.returncode == 0:
                            self._power.changed = True
                            self._status.power_plan_changed = True
                        else:
                            logger.warning("powercfg failed: %s", result.stderr.strip())
                    except Exception as exc:
                        logger.warning("Power plan boost failed: %s", exc)

            for process in self._roblox_processes():
                try:
                    previous = process.nice()
                    process.nice(psutil.HIGH_PRIORITY_CLASS)
                    self._priorities.append(
                        _PriorityState(pid=process.pid, previous_priority=previous)
                    )
                except (psutil.Error, OSError) as exc:
                    logger.debug("Cannot boost pid %s: %s", process.pid, exc)

            self._status.boosted_processes = len(self._priorities)
            self._active = True
            return self.report()

    def restore(self) -> dict[str, Any]:
        with self._lock:
            if not self._active:
                return self.report()
            for item in self._priorities:
                try:
                    process = psutil.Process(item.pid)
                    process.nice(item.previous_priority)
                except (psutil.Error, OSError):
                    continue
            self._priorities.clear()

            if self._power.changed and self._power.previous_guid:
                try:
                    _run_hidden(
                        ["powercfg", "/setactive", self._power.previous_guid]
                    )
                except Exception:
                    logger.warning("Cannot restore power plan", exc_info=True)
            self._power = _PowerState()

            self._active = False
            self._status = ProtocolStatus()
            return self.report()

    def toggle(self) -> dict[str, Any]:
        return self.restore() if self._active else self.engage()

    def report(self) -> dict[str, Any]:
        return {
            "active": self._active,
            "power_plan_changed": self._status.power_plan_changed,
            "boosted_processes": self._status.boosted_processes,
            "previous_power_plan": self._power.previous_guid,
        }


class BossKeyProtocol:
    """Hide selected windows and mute audio sessions; fully reversible."""

    def __init__(self, hotkey: str = "ctrl+shift+h") -> None:
        self.hotkey = hotkey
        self._lock = threading.RLock()
        self._windows: list[_WindowState] = []
        self._audio: list[_AudioState] = []
        self._active = False
        self._mute_fallback = False
        self._status = ProtocolStatus()
        self._hotkey_thread: threading.Thread | None = None
        self._stop_hotkey = threading.Event()
        self._last_hotkey_at = 0.0
        self._com_state = threading.local()

    @property
    def active(self) -> bool:
        return self._active

    @property
    def status(self) -> ProtocolStatus:
        return self._status

    # -- window discovery --------------------------------------------------
    @staticmethod
    def _window_title(hwnd: int) -> str:
        length = int(_user32.GetWindowTextLengthW(hwnd))
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _collect_windows(self) -> list[_WindowState]:
        if not _IS_WINDOWS:
            return []
        foreground = int(_user32.GetForegroundWindow())
        candidates: list[_WindowState] = []
        own_pid = os.getpid()

        def consider(hwnd: int) -> None:
            if not hwnd or not _user32.IsWindowVisible(hwnd):
                return
            title = self._window_title(hwnd).strip()
            if not title:
                return
            pid = ctypes.c_ulong()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pid_value = int(pid.value)
            if pid_value == own_pid:
                return
            try:
                process = psutil.Process(pid_value).name().lower()
            except (psutil.Error, ValueError):
                return
            if process not in (_ROBLOX_PROCESSES | _BROWSER_PROCESSES):
                if hwnd != foreground:
                    return
            if any(item.hwnd == hwnd for item in candidates):
                return
            candidates.append(
                _WindowState(
                    hwnd=hwnd,
                    pid=pid_value,
                    process=process,
                    title=title,
                )
            )

        consider(foreground)
        for process in psutil.process_iter(["pid", "name"]):
            try:
                name = (process.info.get("name") or "").lower()
                if name not in (_ROBLOX_PROCESSES | _BROWSER_PROCESSES):
                    continue
                for hwnd in self._top_level_windows(process.pid):
                    consider(hwnd)
            except (psutil.Error, ValueError):
                continue
        return candidates

    @staticmethod
    def _top_level_windows(pid: int) -> list[int]:
        handles: list[int] = []
        enum_proc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
        )

        def callback(hwnd: int, _lparam: int) -> bool:
            window_pid = ctypes.c_ulong()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if int(window_pid.value) == pid:
                handles.append(int(hwnd))
            return True

        try:
            _user32.EnumWindows(enum_proc(callback), 0)
        except Exception:
            logger.debug("EnumWindows failed", exc_info=True)
        return handles

    # -- audio -------------------------------------------------------------
    def _ensure_com(self) -> None:
        if getattr(self._com_state, "ready", False):
            return
        try:
            import comtypes

            comtypes.CoInitialize()
            self._com_state.ready = True
        except Exception:
            logger.debug("COM init skipped", exc_info=True)

    def _mute_all(self) -> int:
        self._ensure_com()
        muted = 0
        try:
            from pycaw.pycaw import AudioUtilities
        except ImportError:
            self._fallback_mute(True)
            self._mute_fallback = True
            return 0

        try:
            sessions = AudioUtilities.GetAllSessions()
        except Exception:
            logger.exception("Cannot enumerate audio sessions")
            self._fallback_mute(True)
            self._mute_fallback = True
            return 0

        for index, session in enumerate(sessions):
            try:
                if session.Process is None:
                    continue
                volume = session.SimpleAudioVolume
                if volume is None:
                    continue
                current = float(volume.GetMasterVolume())
                was_muted = bool(volume.GetMute())
                session_id = f"{getattr(session, 'SessionIdentifier', '') or index}"
                self._audio.append(
                    _AudioState(
                        session_id=session_id,
                        volume=current,
                        muted=was_muted,
                    )
                )
                volume.SetMute(1, None)
                muted += 1
            except Exception:
                logger.debug("Cannot mute session %s", index, exc_info=True)
        return muted

    def _restore_audio(self) -> None:
        if self._mute_fallback:
            self._fallback_mute(False)
            self._mute_fallback = False
            return
        if not self._audio:
            return
        self._ensure_com()
        try:
            from pycaw.pycaw import AudioUtilities

            sessions = AudioUtilities.GetAllSessions()
            by_id: dict[str, Any] = {}
            for index, session in enumerate(sessions):
                key = f"{getattr(session, 'SessionIdentifier', '') or index}"
                by_id[key] = session
            for state in self._audio:
                session = by_id.get(state.session_id)
                if session is None:
                    continue
                try:
                    session.SimpleAudioVolume.SetMasterVolume(state.volume, None)
                    session.SimpleAudioVolume.SetMute(int(state.muted), None)
                except Exception:
                    logger.debug("Cannot restore audio session", exc_info=True)
        except Exception:
            logger.exception("Audio restore failed")
        finally:
            self._audio.clear()

    @staticmethod
    def _fallback_mute(mute: bool) -> None:
        """Last-resort system mute key (toggle only, used carefully)."""
        if not _IS_WINDOWS:
            return
        try:
            vk_mute = 0xAD
            _user32.keybd_event(vk_mute, 0, 0, 0)
            _user32.keybd_event(vk_mute, 0, 2, 0)
        except Exception:
            logger.debug("System mute key failed", exc_info=True)

    # -- engage / restore --------------------------------------------------
    def engage(self) -> dict[str, Any]:
        if not _IS_WINDOWS:
            raise RuntimeError("Boss Key доступен только в Windows")
        with self._lock:
            if self._active:
                return self.report()
            self._windows = self._collect_windows()
            hidden = 0
            for item in self._windows:
                try:
                    _user32.ShowWindow(item.hwnd, _SW_HIDE)
                    hidden += 1
                except Exception:
                    logger.debug("Cannot hide hwnd %s", item.hwnd, exc_info=True)
            muted = self._mute_all()
            self._active = True
            self._status = ProtocolStatus(
                boss_mode=True,
                hidden_windows=hidden,
                muted_sessions=muted,
            )
            logger.info("Boss mode engaged: %s windows, %s sessions", hidden, muted)
            return self.report()

    def restore(self) -> dict[str, Any]:
        with self._lock:
            if not self._active:
                return self.report()
            for item in self._windows:
                try:
                    _user32.ShowWindow(item.hwnd, _SW_SHOW)
                    _user32.ShowWindow(item.hwnd, _SW_RESTORE)
                except Exception:
                    logger.debug("Cannot restore hwnd %s", item.hwnd, exc_info=True)
            self._restore_audio()
            self._active = False
            self._status = ProtocolStatus()
            self._windows.clear()
            logger.info("Boss mode restored")
            return self.report()

    def toggle(self) -> dict[str, Any]:
        return self.restore() if self._active else self.engage()

    # -- global hotkey -----------------------------------------------------
    @staticmethod
    def _pressed(vk: int) -> bool:
        return bool(_user32.GetAsyncKeyState(vk) & 0x8000)

    def _hotkey_loop(self) -> None:
        logger.info("Boss-key hotkey listener started (%s)", self.hotkey)
        while not self._stop_hotkey.is_set():
            try:
                if (
                    self._pressed(0x11)  # Ctrl
                    and self._pressed(0x10)  # Shift
                    and self._pressed(0x48)  # H
                ):
                    now = time.monotonic()
                    if now - self._last_hotkey_at > 0.8:
                        self._last_hotkey_at = now
                        self.toggle()
            except Exception:
                logger.exception("Hotkey loop error")
            self._stop_hotkey.wait(0.045)

    def start_hotkey_listener(self) -> None:
        if not _IS_WINDOWS or self._hotkey_thread is not None:
            return
        self._stop_hotkey.clear()
        self._hotkey_thread = threading.Thread(
            target=self._hotkey_loop,
            name="KatyaBossKey",
            daemon=True,
        )
        self._hotkey_thread.start()

    def stop_hotkey_listener(self) -> None:
        self._stop_hotkey.set()
        thread = self._hotkey_thread
        if thread and thread.is_alive():
            thread.join(timeout=1.5)
        self._hotkey_thread = None

    def report(self) -> dict[str, Any]:
        return {
            "active": self._active,
            "hidden_windows": len(self._windows),
            "muted_sessions": len(self._audio),
            "hotkey": self.hotkey,
        }

    def close(self) -> None:
        self.stop_hotkey_listener()
        self.restore()


class MarvelProtocols:
    """Facade used by the HUD and graceful shutdown."""

    def __init__(self) -> None:
        settings = load_settings().get("protocols", {})
        self.overclock = OverclockProtocol()
        self.boss = BossKeyProtocol(str(settings.get("boss_key", "ctrl+shift+h")))
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.boss.start_hotkey_listener()
        self._started = True

    def stop(self) -> None:
        self.boss.close()
        self.overclock.restore()
        self._started = False

    def status(self) -> dict[str, Any]:
        return {
            "overclock": self.overclock.report(),
            "boss": self.boss.report(),
        }
