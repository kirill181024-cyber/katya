"""
Echo Guard — half-duplex protection against the assistant hearing itself.

The guard combines three layers:
1. A hard gate while TTS is actually playing.
2. A short cooldown after playback (room reverb / Bluetooth latency).
3. Text fingerprint comparison of a freshly recognised phrase against the
   last things Katya said (protects against delayed loopback and TV bleed).

It is deliberately dependency-free and thread-safe so it can be used from the
sounddevice callback thread, the UI thread and the asyncio runtime.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from difflib import SequenceMatcher
from typing import Deque

_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


def normalize_text(value: str) -> str:
    value = value.lower().replace("ё", "е")
    value = _WORD_RE.sub(" ", value)
    return " ".join(value.split())


def _tokens(value: str) -> set[str]:
    return {token for token in normalize_text(value).split() if len(token) > 1}


class EchoGuard:
    """Coordinates microphone gating around Katya's own speech."""

    def __init__(
        self,
        cooldown_seconds: float = 0.75,
        history_size: int = 12,
        similarity_threshold: float = 0.80,
    ) -> None:
        self._lock = threading.RLock()
        self._cooldown = max(0.0, float(cooldown_seconds))
        self._similarity_threshold = min(1.0, max(0.1, float(similarity_threshold)))
        self._speaking = False
        self._quiet_until = 0.0
        self._speech_started_at = 0.0
        self._phrases: Deque[str] = deque(maxlen=max(1, history_size))
        self._token_sets: Deque[set[str]] = deque(maxlen=max(1, history_size))

    # -- playback lifetime -------------------------------------------------
    def begin_speech(self, text: str = "") -> None:
        with self._lock:
            self._speaking = True
            self._speech_started_at = time.monotonic()
            if text.strip():
                normalized = normalize_text(text)
                if normalized:
                    self._phrases.append(normalized)
                    self._token_sets.append(_tokens(text))

    def end_speech(self) -> None:
        with self._lock:
            self._speaking = False
            self._quiet_until = time.monotonic() + self._cooldown

    def suppress_for(self, seconds: float) -> None:
        """Extend the quiet window, e.g. while a game cutscene is playing."""
        with self._lock:
            self._quiet_until = max(self._quiet_until, time.monotonic() + max(0.0, seconds))

    # -- queries -----------------------------------------------------------
    @property
    def is_speaking(self) -> bool:
        with self._lock:
            return self._speaking

    def is_mic_gated(self) -> bool:
        with self._lock:
            return self._speaking or time.monotonic() < self._quiet_until

    def remaining_cooldown(self) -> float:
        with self._lock:
            return max(0.0, self._quiet_until - time.monotonic())

    def is_probable_echo(self, text: str) -> bool:
        """Return True when `text` looks like a delayed copy of Katya's voice."""
        candidate = normalize_text(text)
        if len(candidate) < 4:
            return False

        with self._lock:
            phrases = list(self._phrases)
            token_sets = list(self._token_sets)

        candidate_tokens = _tokens(text)
        for phrase, phrase_tokens in zip(phrases, token_sets):
            if candidate == phrase:
                return True
            if len(candidate) > 8 and len(phrase) > 8:
                if SequenceMatcher(None, candidate, phrase).ratio() >= self._similarity_threshold:
                    return True
            if candidate_tokens and phrase_tokens:
                overlap = len(candidate_tokens & phrase_tokens) / len(candidate_tokens | phrase_tokens)
                if overlap >= 0.72 and len(candidate_tokens & phrase_tokens) >= 3:
                    return True
        return False

    def should_ignore(self, text: str, require_gate: bool = False) -> bool:
        """
        Full decision used by the STT callback.

        `require_gate=True` makes the guard strict: any audio during the gate is
        discarded even if text does not match (useful for noisy rooms).
        """
        if self.is_mic_gated():
            return True if require_gate else self.is_probable_echo(text)
        return self.is_probable_echo(text)

    def reset(self) -> None:
        with self._lock:
            self._speaking = False
            self._quiet_until = 0.0
            self._speech_started_at = 0.0
            self._phrases.clear()
            self._token_sets.clear()

    def snapshot(self) -> dict[str, float | int | bool]:
        with self._lock:
            return {
                "speaking": self._speaking,
                "cooldown": round(self.remaining_cooldown_locked(), 2),
                "phrases": len(self._phrases),
                "speech_age": round(
                    time.monotonic() - self._speech_started_at, 2
                )
                if self._speech_started_at
                else 0.0,
            }

    def remaining_cooldown_locked(self) -> float:
        return max(0.0, self._quiet_until - time.monotonic())


_GLOBAL_GUARD = EchoGuard()


def get_echo_guard() -> EchoGuard:
    """Return the process-wide guard used by STT and TTS."""
    return _GLOBAL_GUARD
