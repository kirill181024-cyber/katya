"""Глобальная конфигурация Katya 2.10."""

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "qwen2.5:7b"
VISION_MODEL = "llava"
VERSION = "2.10"

# Тайм-ауты (секунды)
CHAT_TIMEOUT = 240
VISION_TIMEOUT = 180

# Протокол Cyber-Coach: интервал захвата кадров (сек)
COACH_INTERVAL = 3.5
# Размер кадра, отправляемого в vision-модель
COACH_MAX_WIDTH = 1280
