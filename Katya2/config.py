"""Глобальная конфигурация Katya 2.10."""

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "gemma3:4b"
VISION_MODEL = "gemma3:4b"
VERSION = "2.10.1"

# --- Ускорение на GPU (NVIDIA) ---
# num_gpu=999 => выгружать все слои на видеокарту.
# Малый контекст (2048) нужен, чтобы модель + KV-кэш влезали в 6 ГБ VRAM.
NUM_GPU = 999
TEXT_NUM_CTX = 4096
VISION_NUM_CTX = 2048

# Тайм-ауты (секунды)
CHAT_TIMEOUT = 240
VISION_TIMEOUT = 600

# Протокол Cyber-Coach: интервал захвата кадров (сек)
COACH_INTERVAL = 3.5
# Размер кадра, отправляемого в vision-модель
COACH_MAX_WIDTH = 1280
