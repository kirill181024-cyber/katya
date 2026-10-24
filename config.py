"""
Katya 2.11.0 — Marvel-Swarm Edition
Central configuration and persistent settings.

Security note
-------------
This file intentionally contains NO hard-coded API keys or GitHub tokens.
Secrets are read from environment variables or from the per-user settings
file under %LOCALAPPDATA%\\Katya, which is excluded from Git.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

APP_NAME = "Katya"
APP_VERSION = "2.11.0"
CODENAME = "Marvel-Swarm Edition"
APP_TITLE = f"КАТЯ {APP_VERSION} // MARVEL-SWARM"

ROOT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = ROOT_DIR / "assets"
SKILLS_DIR = ROOT_DIR / "skills"
CORE_DIR = ROOT_DIR / "core"
UI_DIR = ROOT_DIR / "ui"

_local_appdata = os.getenv("LOCALAPPDATA")
DATA_DIR = Path(
    os.getenv(
        "KATYA_DATA_DIR",
        str(Path(_local_appdata) / "Katya") if _local_appdata else str(ROOT_DIR / "data"),
    )
)
def _runtime_paths(base: Path) -> tuple[Path, Path, Path, Path, Path]:
    paths = (
        base / "models",
        base / "cache",
        base / "logs",
        base / "backups",
        base / "settings.json",
    )
    for directory in (base, paths[0], paths[1], paths[2], paths[3]):
        directory.mkdir(parents=True, exist_ok=True)
    return paths


try:
    MODELS_DIR, CACHE_DIR, LOG_DIR, BACKUP_DIR, SETTINGS_FILE = _runtime_paths(DATA_DIR)
except OSError:
    # Portable fallback for locked-down Windows profiles / sandboxes.
    DATA_DIR = ROOT_DIR / "data"
    MODELS_DIR, CACHE_DIR, LOG_DIR, BACKUP_DIR, SETTINGS_FILE = _runtime_paths(DATA_DIR)

# ---------------------------------------------------------------------------
# Ollama / local AI
# ---------------------------------------------------------------------------
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_CHAT_URL = f"{OLLAMA_URL}/api/chat"
OLLAMA_TAGS_URL = f"{OLLAMA_URL}/api/tags"
OLLAMA_PULL_URL = f"{OLLAMA_URL}/api/pull"

MODEL_FAST = os.getenv("KATYA_MODEL_FAST", "qwen2.5:7b")
MODEL_LIGHT = os.getenv("KATYA_MODEL_LIGHT", "gemma3:4b")
MODEL_VISION = os.getenv("KATYA_MODEL_VISION", "llava:latest")
OLLAMA_MODELS = {
    "fast": MODEL_FAST,
    "light": MODEL_LIGHT,
    "vision": MODEL_VISION,
}

# ---------------------------------------------------------------------------
# Cloud providers
# ---------------------------------------------------------------------------
PROVIDERS: dict[str, dict[str, Any]] = {
    "local": {
        "label": "Локальный ИИ",
        "kind": "ollama",
        "endpoint": OLLAMA_CHAT_URL,
        "model": MODEL_FAST,
        "vision_model": MODEL_VISION,
        "env_key": "",
    },
    "claude": {
        "label": "Claude",
        "kind": "anthropic",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "model": os.getenv("KATYA_CLAUDE_MODEL", "claude-sonnet-4-5"),
        "vision_model": os.getenv("KATYA_CLAUDE_MODEL", "claude-sonnet-4-5"),
        "env_key": "ANTHROPIC_API_KEY",
    },
    "chatgpt": {
        "label": "ChatGPT",
        "kind": "openai",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "model": os.getenv("KATYA_OPENAI_MODEL", "gpt-4o-mini"),
        "vision_model": os.getenv("KATYA_OPENAI_MODEL", "gpt-4o-mini"),
        "env_key": "OPENAI_API_KEY",
    },
    "deepseek": {
        "label": "DeepSeek",
        "kind": "openai",
        "endpoint": "https://api.deepseek.com/chat/completions",
        "model": os.getenv("KATYA_DEEPSEEK_MODEL", "deepseek-chat"),
        "vision_model": os.getenv("KATYA_DEEPSEEK_MODEL", "deepseek-chat"),
        "env_key": "DEEPSEEK_API_KEY",
    },
}

DEFAULT_PROVIDER = "local"

# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------
TTS_VOICE = os.getenv("KATYA_TTS_VOICE", "ru-RU-DmitryNeural")
TTS_RATE = os.getenv("KATYA_TTS_RATE", "+8%")
TTS_VOLUME = os.getenv("KATYA_TTS_VOLUME", "+0%")
SAMPLE_RATE = 16_000
BLOCK_SIZE = 8_000
VOSK_MODEL_NAME = "vosk-model-small-ru-0.22"
VOSK_MODEL_URL = (
    f"https://alphacephei.com/vosk/models/{VOSK_MODEL_NAME}.zip"
)
VOSK_MODEL_DIR = MODELS_DIR / VOSK_MODEL_NAME

WAKE_WORDS = ("катя", "катя.", "katya", "кэт")
ASSISTANT_SYSTEM_PROMPT = (
    "Ты — Катя 2.11.0, дерзкий голосовой ИИ-ассистент в стиле Пятницы из Marvel. "
    "Отвечай по-русски, коротко и уверенно. В обычном диалоге — 1-3 предложения, "
    "без списков и markdown, потому что ответ озвучивается. Не выдумывай факты. "
    "Если задача требует действия в системе — предложи конкретную команду."
)

# ---------------------------------------------------------------------------
# Cyber-Coach
# ---------------------------------------------------------------------------
COACH_INTERVAL_SECONDS = 3.0
COACH_MIN_GAP_SECONDS = 3.0
COACH_PROMPT = (
    "Ты — дерзкий тренер по Roblox с позывным Катя. Посмотри на кадр и определи "
    "класс персонажа: Тень (Shadow) или Воин (Warrior). Оцени кулдауны и заряды "
    "способностей по UI. Дай ОДИН короткий агрессивный совет по комбо на русском, "
    "максимум 18 слов. Если бой не идёт — скажи, где занять позицию. "
    "Не описывай картинку, сразу давай совет."
)
ROBLOX_PROCESS_NAMES = {"robloxplayerbeta.exe", "robloxplayerlauncher.exe", "robloxplayer.exe"}
ROBLOX_TITLE_HINTS = ("roblox", "роблокс")

# ---------------------------------------------------------------------------
# Repository (publishing credentials are NEVER stored here)
# ---------------------------------------------------------------------------
GITHUB_USERNAME = os.getenv("KATYA_GITHUB_USER", "kirill181024-cyber")
GITHUB_REPO = os.getenv("KATYA_GITHUB_REPO", "katya")
GITHUB_URL = f"https://github.com/{GITHUB_USERNAME}/{GITHUB_REPO}"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")  # ephemeral, env-only by design

# ---------------------------------------------------------------------------
# Persisted settings
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS: dict[str, Any] = {
    "version": APP_VERSION,
    "provider": DEFAULT_PROVIDER,
    "api_keys": {},
    "models": {
        "local": MODEL_FAST,
        "claude": PROVIDERS["claude"]["model"],
        "chatgpt": PROVIDERS["chatgpt"]["model"],
        "deepseek": PROVIDERS["deepseek"]["model"],
    },
    "voice": {
        "enabled": True,
        "voice": TTS_VOICE,
        "rate": TTS_RATE,
        "volume": TTS_VOLUME,
        "input_device": None,
        "output_device": None,
        "wake_word_required": False,
    },
    "coach": {
        "enabled": False,
        "interval": COACH_INTERVAL_SECONDS,
        "muted": False,
    },
    "protocols": {
        "auto_restore": True,
        "boss_key": "ctrl+shift+h",
        "overclock": False,
    },
    "ui": {
        "appearance": "dark",
        "geometry": "1220x800",
        "always_on_top": False,
    },
    "privacy": {
        "store_cloud_keys_locally": True,
        "capture_only_when_roblox_focused": True,
    },
}

_settings_lock = threading.RLock()
_settings_cache: dict[str, Any] | None = None


def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_settings() -> dict[str, Any]:
    """Load settings, merging missing fields with defaults."""
    global _settings_cache
    with _settings_lock:
        if _settings_cache is not None:
            return copy.deepcopy(_settings_cache)

        loaded: dict[str, Any] = {}
        if SETTINGS_FILE.exists():
            try:
                raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    loaded = raw
            except (OSError, ValueError):
                loaded = {}

        merged = _deep_merge(DEFAULT_SETTINGS, loaded)
        _settings_cache = merged
        return copy.deepcopy(merged)


def save_settings(settings: dict[str, Any]) -> None:
    """Atomically persist settings with restrictive best-effort permissions."""
    global _settings_cache
    with _settings_lock:
        merged = _deep_merge(DEFAULT_SETTINGS, settings)
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = SETTINGS_FILE.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, SETTINGS_FILE)
        _settings_cache = merged
        try:
            os.chmod(SETTINGS_FILE, 0o600)
        except OSError:
            pass


def update_settings(**sections: Any) -> dict[str, Any]:
    """Merge top-level sections into settings and persist them."""
    settings = load_settings()
    for key, value in sections.items():
        if isinstance(value, dict) and isinstance(settings.get(key), dict):
            settings[key] = _deep_merge(settings[key], value)
        else:
            settings[key] = value
    save_settings(settings)
    return settings


def get_provider_config(provider: str | None = None) -> dict[str, Any]:
    settings = load_settings()
    name = provider or settings.get("provider", DEFAULT_PROVIDER)
    if name not in PROVIDERS:
        name = DEFAULT_PROVIDER
    data = copy.deepcopy(PROVIDERS[name])
    data["name"] = name
    data["model"] = settings.get("models", {}).get(name, data["model"])
    return data


def get_api_key(provider: str | None = None) -> str:
    settings = load_settings()
    name = provider or settings.get("provider", DEFAULT_PROVIDER)
    env_name = PROVIDERS.get(name, {}).get("env_key", "")
    if env_name and os.getenv(env_name):
        return os.environ[env_name].strip()
    return str(settings.get("api_keys", {}).get(name, "") or "").strip()


def set_api_key(provider: str, value: str) -> None:
    settings = load_settings()
    keys = settings.setdefault("api_keys", {})
    if value:
        keys[provider] = value.strip()
    else:
        keys.pop(provider, None)
    save_settings(settings)


def set_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    update_settings(provider=provider)


def set_model(provider: str, model: str) -> None:
    models = load_settings().get("models", {})
    models[provider] = model.strip()
    update_settings(models=models)


def mask_secret(secret: str) -> str:
    if not secret:
        return "—"
    if len(secret) <= 8:
        return "•" * len(secret)
    return f"{secret[:4]}{'•' * max(4, len(secret) - 8)}{secret[-4:]}"


def ensure_runtime_dirs() -> None:
    for directory in (DATA_DIR, MODELS_DIR, CACHE_DIR, LOG_DIR, BACKUP_DIR):
        directory.mkdir(parents=True, exist_ok=True)
