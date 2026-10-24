"""
Katya Brain — a single async interface over local and cloud LLMs.

Supported backends:
  * Ollama        — qwen2.5:7b / gemma3:4b / llava:latest (vision)
  * Anthropic     — Claude
  * OpenAI        — ChatGPT
  * DeepSeek      — deepseek-chat

Also contains guarded Runtime Self-Evolution: source patches are backed up,
compiled, hot-reloaded with importlib, and rolled back automatically if the
reload fails. Patches require an explicit `approved=True` flag; the language
model can propose code but can never silently rewrite Katya.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import re
import shutil
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque

import requests

from config import (
    ASSISTANT_SYSTEM_PROMPT,
    BACKUP_DIR,
    OLLAMA_CHAT_URL,
    OLLAMA_TAGS_URL,
    OLLAMA_URL,
    ROOT_DIR,
    get_api_key,
    get_provider_config,
    load_settings,
)

logger = logging.getLogger(__name__)


class BrainError(RuntimeError):
    """A user-presentable LLM failure."""


@dataclass(slots=True)
class ChatResponse:
    text: str
    provider: str
    model: str
    latency: float
    raw: dict[str, Any] = field(default_factory=dict)


def _strip_data_url(image: str) -> tuple[str, str]:
    """Return (media_type, base64_data) from raw base64 or a data URL."""
    if image.startswith("data:"):
        header, _, data = image.partition(",")
        media_type = header[5:].split(";")[0] or "image/jpeg"
        return media_type, data
    return "image/jpeg", image


class BaseProvider:
    name = "base"
    kind = "base"

    def __init__(self, config: dict[str, Any], api_key: str = "") -> None:
        self.config = config
        self.api_key = api_key
        self.name = str(config.get("name", self.name))
        self.model = str(config.get("model", ""))
        self.endpoint = str(config.get("endpoint", ""))

    async def chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        images: list[str] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 420,
    ) -> ChatResponse:
        raise NotImplementedError

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.name, "model": self.model}


class OllamaProvider(BaseProvider):
    kind = "ollama"

    def __init__(self, config: dict[str, Any], api_key: str = "") -> None:
        super().__init__(config, api_key)
        self.vision_model = str(config.get("vision_model", self.model))

    async def chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        images: list[str] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 420,
    ) -> ChatResponse:
        started = time.perf_counter()
        payload_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system}
        ]
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            item: dict[str, Any] = {"role": role, "content": content}
            payload_messages.append(item)

        if images and payload_messages:
            # Attach images to the last user message, as required by Ollama.
            for item in reversed(payload_messages):
                if item["role"] == "user":
                    item["images"] = [
                        _strip_data_url(image)[1] for image in images if image
                    ]
                    break

        model = self.model
        if images and self.vision_model:
            model = self.vision_model

        body = {
            "model": model,
            "messages": payload_messages,
            "stream": False,
            # Keep the model in VRAM/RAM between coach frames. Without this
            # every 3-second analysis can trigger a cold 60-100 s reload.
            "keep_alive": "30m",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "top_p": 0.9,
            },
        }

        def request() -> dict[str, Any]:
            response = requests.post(OLLAMA_CHAT_URL, json=body, timeout=(4, 180))
            if response.status_code == 404:
                raise BrainError(
                    f"Модель {model} не найдена в Ollama. Запустите setup_wizard.py "
                    f"или выполните: ollama pull {model}"
                )
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise BrainError(str(data["error"]))
            return data

        try:
            data = await asyncio.to_thread(request)
        except requests.ConnectionError as exc:
            raise BrainError(
                f"Ollama недоступна по адресу {OLLAMA_URL}. Запустите ollama serve."
            ) from exc
        except requests.Timeout as exc:
            raise BrainError("Ollama не ответила вовремя. Модель перегружена?") from exc
        except requests.HTTPError as exc:
            raise BrainError(f"Ollama HTTP {exc.response.status_code}") from exc

        text = str(data.get("message", {}).get("content", "")).strip()
        if not text:
            raise BrainError("Ollama вернула пустой ответ")
        return ChatResponse(
            text=text,
            provider=self.name,
            model=model,
            latency=time.perf_counter() - started,
            raw=data,
        )

    async def health(self) -> dict[str, Any]:
        def probe() -> dict[str, Any]:
            response = requests.get(OLLAMA_TAGS_URL, timeout=3)
            response.raise_for_status()
            data = response.json()
            models = [str(item.get("name", "")) for item in data.get("models", [])]
            return {"ok": True, "models": models, "url": OLLAMA_URL}

        try:
            return await asyncio.to_thread(probe)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "url": OLLAMA_URL}


class OpenAICompatibleProvider(BaseProvider):
    kind = "openai"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        images: list[str] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 420,
    ) -> ChatResponse:
        if not self.api_key:
            raise BrainError(
                f"Не задан API-ключ для {self.name}. Откройте НЕЙРО-СЕТЬ и вставьте ключ."
            )
        started = time.perf_counter()
        payload_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system}
        ]
        for index, message in enumerate(messages):
            role = message.get("role", "user")
            content = message.get("content", "")
            is_last_user = index == len(messages) - 1 and role == "user"
            if images and is_last_user:
                blocks: list[dict[str, Any]] = [{"type": "text", "text": content}]
                for image in images:
                    media_type, data = _strip_data_url(image)
                    blocks.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{data}"},
                        }
                    )
                payload_messages.append({"role": role, "content": blocks})
            else:
                payload_messages.append({"role": role, "content": content})

        body = {
            "model": self.model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        def request() -> dict[str, Any]:
            response = requests.post(
                self.endpoint, json=body, headers=headers, timeout=(5, 90)
            )
            if response.status_code in (401, 403):
                raise BrainError(f"{self.name}: API-ключ отклонён")
            if response.status_code == 429:
                raise BrainError(f"{self.name}: лимит запросов, попробуйте позже")
            if response.status_code >= 400:
                detail = response.text[:300].replace("\n", " ")
                raise BrainError(f"{self.name} HTTP {response.status_code}: {detail}")
            return response.json()

        try:
            data = await asyncio.to_thread(request)
        except requests.Timeout as exc:
            raise BrainError(f"{self.name} не ответил вовремя") from exc
        except requests.ConnectionError as exc:
            raise BrainError(f"Нет соединения с {self.name}") from exc

        try:
            text = str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise BrainError(f"{self.name} вернул неожиданный формат ответа") from exc
        if not text:
            raise BrainError(f"{self.name} вернул пустой ответ")
        return ChatResponse(
            text=text,
            provider=self.name,
            model=self.model,
            latency=time.perf_counter() - started,
            raw=data,
        )


class AnthropicProvider(BaseProvider):
    kind = "anthropic"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        images: list[str] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 420,
    ) -> ChatResponse:
        if not self.api_key:
            raise BrainError("Не задан API-ключ Claude. Откройте НЕЙРО-СЕТЬ.")
        started = time.perf_counter()
        api_messages: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            role = message.get("role", "user")
            if role not in ("user", "assistant"):
                continue
            content = str(message.get("content", ""))
            is_last_user = index == len(messages) - 1 and role == "user"
            if images and is_last_user:
                blocks: list[dict[str, Any]] = [
                    {"type": "text", "text": content}
                ]
                for image in images:
                    media_type, data = _strip_data_url(image)
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": data,
                            },
                        }
                    )
                api_messages.append({"role": role, "content": blocks})
            else:
                api_messages.append({"role": role, "content": content})

        body = {
            "model": self.model,
            "system": system,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        def request() -> dict[str, Any]:
            response = requests.post(
                self.endpoint, json=body, headers=headers, timeout=(5, 90)
            )
            if response.status_code in (401, 403):
                raise BrainError("Claude: API-ключ отклонён")
            if response.status_code >= 400:
                detail = response.text[:300].replace("\n", " ")
                raise BrainError(f"Claude HTTP {response.status_code}: {detail}")
            return response.json()

        try:
            data = await asyncio.to_thread(request)
        except requests.Timeout as exc:
            raise BrainError("Claude не ответил вовремя") from exc
        except requests.ConnectionError as exc:
            raise BrainError("Нет соединения с Claude") from exc

        content = data.get("content", [])
        text = " ".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if not text:
            raise BrainError("Claude вернул пустой ответ")
        return ChatResponse(
            text=text,
            provider=self.name,
            model=self.model,
            latency=time.perf_counter() - started,
            raw=data,
        )


_PROVIDER_CLASSES = {
    "ollama": OllamaProvider,
    "openai": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
}


class Brain:
    """Conversation orchestrator with provider switching and memory."""

    def __init__(
        self,
        system_prompt: str = ASSISTANT_SYSTEM_PROMPT,
        memory_size: int = 16,
    ) -> None:
        self.system_prompt = system_prompt
        self._history: Deque[dict[str, str]] = deque(maxlen=memory_size)
        self._lock = threading.RLock()
        self._last_response: ChatResponse | None = None

    @property
    def last_response(self) -> ChatResponse | None:
        return self._last_response

    def provider_name(self) -> str:
        return str(load_settings().get("provider", "local"))

    def _build_provider(self, provider: str | None = None) -> BaseProvider:
        config = get_provider_config(provider)
        kind = str(config.get("kind", "ollama"))
        cls = _PROVIDER_CLASSES.get(kind)
        if cls is None:
            raise BrainError(f"Неизвестный провайдер: {kind}")
        key = "" if kind == "ollama" else get_api_key(config["name"])
        return cls(config, key)

    def clear_memory(self) -> None:
        with self._lock:
            self._history.clear()

    def history(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._history)

    async def chat(
        self,
        user_text: str,
        images: list[str] | None = None,
        remember: bool = True,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 420,
        provider: str | None = None,
    ) -> ChatResponse:
        user_text = (user_text or "").strip()
        if not user_text and not images:
            raise BrainError("Пустой запрос")

        provider_obj = self._build_provider(provider)
        system = system_prompt or self.system_prompt
        with self._lock:
            history = list(self._history)

        messages = history + [{"role": "user", "content": user_text}]
        result = await provider_obj.chat(
            messages=messages,
            system=system,
            images=images,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._last_response = result
        if remember:
            with self._lock:
                self._history.append({"role": "user", "content": user_text})
                self._history.append(
                    {"role": "assistant", "content": result.text}
                )
        return result

    async def ask(self, user_text: str) -> str:
        return (await self.chat(user_text)).text

    async def health(self, provider: str | None = None) -> dict[str, Any]:
        try:
            provider_obj = self._build_provider(provider)
            return await provider_obj.health()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def list_ollama_models(self) -> list[str]:
        def probe() -> list[str]:
            response = requests.get(OLLAMA_TAGS_URL, timeout=4)
            response.raise_for_status()
            return [
                str(item.get("name", ""))
                for item in response.json().get("models", [])
            ]

        try:
            return await asyncio.to_thread(probe)
        except Exception:
            logger.debug("Ollama model list unavailable", exc_info=True)
            return []


# ---------------------------------------------------------------------------
# Runtime Self-Evolution
# ---------------------------------------------------------------------------
_ALLOWED_MODULES = (
    "core.tts",
    "core.stt",
    "skills.game_analyst",
    "skills.marvel_protocols",
)


class EvolutionError(RuntimeError):
    pass


class SelfEvolution:
    """
    Guarded hot-patching of allow-listed modules.

    Safety properties:
      * only files inside the project and allow-listed modules;
      * every patch is compiled before it replaces the live file;
      * the previous file is backed up under %LOCALAPPDATA%\\Katya\\backups;
      * a failed import triggers an automatic rollback;
      * LLM-proposed patches are never applied without `approved=True`.
    """

    def __init__(self, root: Path = ROOT_DIR) -> None:
        self.root = Path(root).resolve()
        self.backup_dir = BACKUP_DIR
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _module_path(self, module: str) -> Path:
        if module not in _ALLOWED_MODULES:
            raise EvolutionError(f"Модуль {module} не входит в allow-list")
        relative = module.replace(".", "/") + ".py"
        path = (self.root / relative).resolve()
        if not str(path).startswith(str(self.root)):
            raise EvolutionError("Попытка выйти за пределы проекта")
        if not path.exists():
            raise EvolutionError(f"Файл модуля не найден: {path}")
        return path

    def list_modules(self) -> list[str]:
        return list(_ALLOWED_MODULES)

    def read_module(self, module: str) -> str:
        return self._module_path(module).read_text(encoding="utf-8")

    def _new_backup_path(self, module: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return self.backup_dir / f"{module.replace('.', '__')}.{stamp}.py"

    def backup(self, module: str) -> Path:
        source = self._module_path(module)
        target = self._new_backup_path(module)
        shutil.copy2(source, target)
        return target

    def apply_patch(
        self,
        module: str,
        old: str,
        new: str,
        reason: str = "manual",
        approved: bool = False,
    ) -> dict[str, Any]:
        """Replace literal `old` with `new` in an allow-listed module."""
        if not approved:
            raise EvolutionError(
                "Патч не применён: требуется явное подтверждение approved=True"
            )
        if not old or old == new:
            raise EvolutionError("Патч пуст или не изменяет код")
        if old not in self.read_module(module):
            raise EvolutionError("Указанный фрагмент кода не найден")

        with self._lock:
            path = self._module_path(module)
            backup_path = self.backup(module)
            original = path.read_text(encoding="utf-8")
            patched = original.replace(old, new, 1)
            try:
                compile(patched, str(path), "exec")
            except SyntaxError as exc:
                raise EvolutionError(f"Синтаксическая ошибка в патче: {exc}") from exc

            try:
                path.write_text(patched, encoding="utf-8")
                importlib.invalidate_caches()
                if module in sys.modules:
                    importlib.reload(sys.modules[module])
            except Exception as exc:
                path.write_text(original, encoding="utf-8")
                importlib.invalidate_caches()
                if module in sys.modules:
                    try:
                        importlib.reload(sys.modules[module])
                    except Exception:
                        logger.exception("Rollback reload failed for %s", module)
                raise EvolutionError(
                    f"Патч откатан: {exc}. Резервная копия: {backup_path.name}"
                ) from exc

            return {
                "ok": True,
                "module": module,
                "backup": str(backup_path),
                "reason": reason,
                "bytes": len(patched),
            }

    def rollback(self, module: str, backup_path: Path | str) -> dict[str, Any]:
        source = Path(backup_path)
        if not source.exists():
            raise EvolutionError(f"Резервная копия не найдена: {source}")
        with self._lock:
            target = self._module_path(module)
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            importlib.invalidate_caches()
            if module in sys.modules:
                importlib.reload(sys.modules[module])
        return {"ok": True, "module": module, "restored_from": str(source)}

    def heal(self) -> dict[str, Any]:
        """
        Import every allow-listed module; if one is broken, restore its newest
        backup and reload. This runs at startup and from the UI self-check.
        """
        report: dict[str, Any] = {"checked": 0, "healthy": [], "repaired": [], "failed": []}
        for module in _ALLOWED_MODULES:
            report["checked"] += 1
            try:
                if module in sys.modules:
                    importlib.reload(sys.modules[module])
                else:
                    importlib.import_module(module)
                report["healthy"].append(module)
            except Exception as exc:
                logger.exception("Self-healing module %s", module)
                backups = sorted(
                    self.backup_dir.glob(f"{module.replace('.', '__')}.*.py"),
                    key=lambda item: item.stat().st_mtime,
                    reverse=True,
                )
                repaired = False
                for backup in backups:
                    try:
                        target = self._module_path(module)
                        shutil.copy2(backup, target)
                        importlib.invalidate_caches()
                        importlib.import_module(module)
                        report["repaired"].append(
                            {"module": module, "backup": backup.name}
                        )
                        repaired = True
                        break
                    except Exception:
                        continue
                if not repaired:
                    report["failed"].append({"module": module, "error": str(exc)})
        report["ok"] = not report["failed"]
        return report

    async def propose_patch(
        self,
        brain: Brain,
        module: str,
        instruction: str,
    ) -> dict[str, Any]:
        """Ask an LLM for a JSON patch proposal; never applies it."""
        source = self.read_module(module)
        prompt = (
            "Ты — инженер по надёжности Python. Верни СТРОГО JSON без markdown:\n"
            '{"old": "точный фрагмент исходника", "new": "замена", "reason": "..."}\n'
            "Фрагмент old должен встречаться ровно один раз. Не меняй импорты без нужды.\n"
            f"МОДУЛЬ: {module}\nЗАДАЧА: {instruction}\nИСХОДНИК:\n{source[:12000]}"
        )
        response = await brain.chat(
            prompt,
            remember=False,
            system_prompt="Ты возвращаешь только валидный JSON.",
            temperature=0.1,
            max_tokens=1600,
        )
        match = re.search(r"\{.*\}", response.text, re.DOTALL)
        if not match:
            raise EvolutionError("Модель не вернула JSON-патч")
        try:
            proposal = json.loads(match.group(0))
        except ValueError as exc:
            raise EvolutionError("Модель вернула невалидный JSON") from exc
        proposal["module"] = module
        proposal["approved"] = False
        proposal["instruction"] = instruction
        return proposal
