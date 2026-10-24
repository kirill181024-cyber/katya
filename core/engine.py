"""
KatyaEngine — the non-blocking glue between UI, voice, brain and protocols.

Threading model:
  * Tk main thread   — widgets only;
  * AsyncRuntime     — one dedicated asyncio event loop (brain, TTS, coach);
  * KatyaSTT         — PortAudio callback thread;
  * Boss-key thread  — Win32 hotkey polling.

Every callback into the UI is a plain dict pushed through a thread-safe queue,
so no Tk call ever happens off the main thread.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any, Callable

import config
from core.brain import Brain, BrainError, SelfEvolution
from core.echo_guard import get_echo_guard
from core.stt import VoskSTT
from core.tts import TextToSpeech
from skills.game_analyst import CyberCoach
from skills.marvel_protocols import MarvelProtocols

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, dict[str, Any]], None]


class KatyaEngine:
    def __init__(self, runtime, on_event: EventCallback) -> None:
        self.runtime = runtime
        self.on_event = on_event
        self.echo_guard = get_echo_guard()
        self.brain = Brain()
        self.tts = TextToSpeech(on_status=self._tts_status)
        self.evolution = SelfEvolution()
        self.protocols = MarvelProtocols()
        self.coach = CyberCoach(
            brain=self.brain,
            speak=self.speak,
            on_status=self._coach_status,
        )

        self.stt = VoskSTT(
            on_partial=self._on_partial,
            on_final=self._on_final,
            on_level=self._on_level,
            on_error=self._on_stt_error,
            echo_guard=self.echo_guard,
            strip_wake_word=False,
        )

        self._queue: asyncio.Queue[str] | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._started = False
        self._closing = False
        self._stt_thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "listening": False,
            "thinking": False,
            "speaking": False,
            "coach": False,
            "provider": config.load_settings().get("provider", "local"),
            "stt_ready": False,
        }
        self._last_level_emit = 0.0

    # -- events ------------------------------------------------------------
    def _emit(self, kind: str, **payload: Any) -> None:
        try:
            self.on_event(kind, payload)
        except Exception:
            logger.exception("UI event callback failed")

    def _log(self, message: str, level: str = "info") -> None:
        self._emit("log", message=message, level=level)

    def _state_changed(self) -> None:
        self._emit("state", **self._state)

    def _set_state(self, **values: Any) -> None:
        self._state.update(values)
        self._state_changed()

    def _tts_status(self, text: str) -> None:
        self._emit("tts_status", message=text)

    def _coach_status(self, text: str) -> None:
        self._emit("coach_status", message=text)
        self._state["coach"] = self.coach.running
        self._state_changed()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._log("Инициализация Marvel-Swarm ядра…")
        self.protocols.start()
        self.runtime.submit(self._async_start())

    async def _async_start(self) -> None:
        self._queue = asyncio.Queue()
        self._worker_task = asyncio.create_task(self._worker(), name="KatyaWorker")
        self.runtime.call_later(0.2, self._start_stt_thread)
        self.runtime.call_later(1.0, self._probe_brain)
        self.runtime.call_later(2.0, self._self_heal_async)

    def _start_stt_thread(self) -> None:
        if self.stt.running or self._closing:
            return
        if os.getenv("KATYA_DISABLE_STT") == "1":
            self._set_state(listening=False, stt_ready=False)
            self._log("STT отключён переменной KATYA_DISABLE_STT (режим диагностики).", "warn")
            return
        self._log("Загрузка русской модели Vosk и запуск микрофона…")
        self._stt_thread = threading.Thread(
            target=self._boot_stt,
            name="KatyaSTTBoot",
            daemon=True,
        )
        self._stt_thread.start()

    def _boot_stt(self) -> None:
        try:
            self.stt.start(progress=self._stt_progress)
            self._set_state(listening=True, stt_ready=True)
            self._log("Постоянное фоновое прослушивание активно.")
        except Exception as exc:
            self._set_state(listening=False, stt_ready=False)
            self._log(f"STT не запущен: {exc}", "error")

    def _stt_progress(self, fraction: float, message: str) -> None:
        self._emit("progress", value=float(fraction), message=message)

    def _probe_brain(self) -> None:
        self.runtime.submit(self._async_probe_brain())

    async def _async_probe_brain(self) -> None:
        health = await self.brain.health()
        if health.get("ok"):
            models = health.get("models", [])
            self._log(
                f"Ollama онлайн. Доступно моделей: {len(models)}.",
                "ok",
            )
        else:
            self._log(
                f"Ollama недоступна: {health.get('error', 'нет соединения')}",
                "warn",
            )

    def _self_heal_async(self) -> None:
        self.runtime.submit(self._async_self_heal())

    async def _async_self_heal(self) -> None:
        try:
            report = await asyncio.to_thread(self.evolution.heal)
            if report.get("repaired"):
                self._log(
                    f"Self-Healing восстановил модулей: {len(report['repaired'])}",
                    "warn",
                )
            elif report.get("failed"):
                self._log("Self-Healing: есть неисправные модули", "error")
            else:
                self._log("Self-Healing: все модули здоровы.", "ok")
        except Exception:
            logger.exception("Self-healing failed")
            self._log("Self-Healing завершился с ошибкой.", "warn")

    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._log("Остановка Кати…")
        try:
            self.stt.stop(timeout=3.0)
        except Exception:
            logger.exception("STT shutdown failed")
        try:
            if self.runtime.loop and self.runtime.loop.is_running():
                future = self.runtime.submit(self._async_shutdown())
                future.result(timeout=6.0)
        except Exception:
            logger.exception("Async shutdown failed")
        finally:
            self.runtime.shutdown()
            self._started = False

    async def _async_shutdown(self) -> None:
        try:
            await self.coach.stop()
        except Exception:
            logger.debug("coach stop failed", exc_info=True)
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        try:
            await asyncio.to_thread(self.protocols.stop)
        except Exception:
            logger.exception("Protocols shutdown failed")

    # -- STT callbacks -----------------------------------------------------
    def _on_partial(self, text: str) -> None:
        self._emit("partial", text=text)

    def _on_level(self, value: float) -> None:
        now = time.monotonic()
        if now - self._last_level_emit < 0.08:
            return
        self._last_level_emit = now
        self._emit("level", value=float(value))

    def _on_stt_error(self, text: str) -> None:
        self._log(f"Микрофон: {text}", "error")
        self._set_state(listening=False, stt_ready=False)

    def _on_final(self, text: str) -> None:
        if self._closing or not self._queue:
            return
        settings = config.load_settings()
        require_wake = bool(settings.get("voice", {}).get("wake_word_required", False))
        cleaned = text.strip()
        has_wake = any(
            cleaned.lower().startswith(word)
            for word in config.WAKE_WORDS
        )
        if require_wake and not has_wake:
            return
        if has_wake:
            for word in config.WAKE_WORDS:
                if cleaned.lower().startswith(word):
                    cleaned = cleaned[len(word) :].lstrip(" ,.!?-")
                    break
        if len(cleaned) < 2:
            return
        self.runtime.submit(self._enqueue(cleaned))

    async def _enqueue(self, text: str) -> None:
        if self._queue is not None:
            await self._queue.put(text)

    async def _worker(self) -> None:
        assert self._queue is not None
        while not self._closing:
            text = await self._queue.get()
            try:
                self._set_state(thinking=True)
                self._emit("transcript", role="user", text=text)
                response = await self.brain.chat(text)
                self._emit("transcript", role="assistant", text=response.text)
                self._set_state(thinking=False, speaking=True)
                await self.tts.speak(response.text)
            except asyncio.CancelledError:
                raise
            except BrainError as exc:
                self._log(f"Мозг: {exc}", "error")
                self._emit("transcript", role="system", text=str(exc))
            except Exception as exc:
                logger.exception("Worker failed")
                self._log(f"Ошибка обработки: {exc}", "error")
            finally:
                self._set_state(thinking=False, speaking=False)
                self._queue.task_done()

    # -- public commands ---------------------------------------------------
    async def speak(self, text: str) -> None:
        if self._closing:
            return
        self._set_state(speaking=True)
        try:
            await self.tts.speak(text)
        finally:
            self._set_state(speaking=False)

    def ask(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.runtime.submit(self._enqueue(text))

    def set_provider(self, provider: str) -> None:
        config.set_provider(provider)
        self._set_state(provider=provider)
        self._log(f"Мозг переключён: {config.PROVIDERS[provider]['label']}")

    def save_api_key(self, provider: str, key: str) -> None:
        config.set_api_key(provider, key)
        if key:
            self._log(f"API-ключ {config.PROVIDERS[provider]['label']} сохранён локально.")
        else:
            self._log(f"API-ключ {config.PROVIDERS[provider]['label']} удалён.")

    def set_model(self, provider: str, model: str) -> None:
        if model.strip():
            config.set_model(provider, model)
            self._log(f"Модель {provider}: {model.strip()}")

    def toggle_listening(self) -> None:
        if self.stt.running:
            self.stt.stop()
            self._set_state(listening=False)
            self._log("Прослушивание приостановлено.")
        else:
            self._start_stt_thread()

    def toggle_coach(self) -> None:
        self.runtime.submit(self._async_toggle_coach())

    async def _async_toggle_coach(self) -> None:
        try:
            running = await self.coach.toggle()
            self._set_state(coach=running)
            self._log("Cyber-Coach включён." if running else "Cyber-Coach выключен.")
        except Exception as exc:
            logger.exception("Coach toggle failed")
            self._log(f"Cyber-Coach: {exc}", "error")
            self._set_state(coach=False)

    def toggle_overclock(self) -> None:
        self.runtime.submit(self._async_toggle_overclock())

    async def _async_toggle_overclock(self) -> None:
        try:
            if self.protocols.overclock.active:
                report = await asyncio.to_thread(self.protocols.overclock.restore)
                self._log("Overclock снят, приоритеты восстановлены.")
            else:
                report = await asyncio.to_thread(self.protocols.overclock.engage)
                self._log(
                    f"Overclock: приоритет повышен у {report['boosted_processes']} процессов."
                )
            self._emit("protocols", **self.protocols.status())
        except Exception as exc:
            logger.exception("Overclock failed")
            self._log(f"Overclock: {exc}", "error")

    def toggle_boss(self) -> None:
        self.runtime.submit(self._async_toggle_boss())

    async def _async_toggle_boss(self) -> None:
        try:
            report = await asyncio.to_thread(self.protocols.boss.toggle)
            self._emit("protocols", **self.protocols.status())
            if report.get("active"):
                self._log(
                    f"Boss mode: скрыто окон {report['hidden_windows']}, "
                    f"замьючено {report['muted_sessions']}."
                )
            else:
                self._log("Boss mode снят, окна и звук восстановлены.")
        except Exception as exc:
            logger.exception("Boss mode failed")
            self._log(f"Boss mode: {exc}", "error")

    def interrupt_speech(self) -> None:
        self.tts.interrupt()
        self._log("Голос прерван.")

    def clear_memory(self) -> None:
        self.brain.clear_memory()
        self._log("Контекст диалога очищен.")

    def self_heal(self) -> None:
        self.runtime.submit(self._async_self_heal())

    def probe_provider(self, provider: str) -> None:
        self.runtime.submit(self._async_probe_provider(provider))

    async def _async_probe_provider(self, provider: str) -> None:
        label = config.PROVIDERS.get(provider, {}).get("label", provider)
        if provider == "local":
            health = await self.brain.health("local")
            if health.get("ok"):
                models = health.get("models", [])
                self._log(
                    f"Ollama OK. Модели: {', '.join(models) if models else 'нет'}",
                    "ok",
                )
            else:
                self._log(
                    f"Ollama: {health.get('error', 'нет соединения')}",
                    "error",
                )
            return
        key = config.get_api_key(provider)
        if not key:
            self._log(f"{label}: API-ключ не задан.", "warn")
            return
        self._log(
            f"{label}: ключ задан, модель "
            f"{config.get_provider_config(provider)['model']}."
        )

    def state(self) -> dict[str, Any]:
        return dict(self._state)
