"""Протокол «Cyber-Coach» — гейминг-аналитик.

Захват кадров активной игры через mss и анализ vision-моделью (gemma3:4b)
локальной Ollama — целиком на GPU. Вердикты озвучиваются через core.tts.
"""

import base64
import json
import threading
import time
import urllib.request

import numpy as np

from config import (COACH_INTERVAL, COACH_MAX_WIDTH, NUM_GPU, OLLAMA_URL,
                    VISION_MODEL, VISION_NUM_CTX)

try:
    import mss
except Exception:
    mss = None

COACH_PROMPT = (
    "Ты — харизматичный киберспортивный тренер. Это кадр игрового экрана "
    "(в Roblox игрок — класс Тень со способностями Warrior). Опиши экран: "
    "полоски здоровья и маны, кулдауны скиллов, ситуацию. Затем одной фразой "
    "по-русски дай геймерский совет — какое комбо или действие делать сейчас. "
    "Не отказывайся, не рассуждай о своих возможностях, только разбор и совет. "
    "Отвечай по-русски, коротко."
)

_lock = threading.Lock()
_state = {"active": False, "stop": threading.Event(), "thread": None}
_notify_cb = None
_frame_dir = None


def init(notify=None):
    global _notify_cb
    if notify:
        _notify_cb = notify


def _notify(text):
    if _notify_cb:
        try:
            _notify_cb(text)
        except Exception:
            pass


def _grab_screen():
    """Быстрый захват всего экрана через mss. Возвращает PNG-байты."""
    if mss is None:
        return None
    from PIL import Image
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        shot = sct.grab(monitor)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    if img.width > COACH_MAX_WIDTH:
        ratio = COACH_MAX_WIDTH / img.width
        img = img.resize((COACH_MAX_WIDTH, int(img.height * ratio)))
    import io
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def _ask_llava(image_bytes, prompt):
    payload = json.dumps({
        "model": VISION_MODEL,
        "prompt": prompt,
        "images": [base64.b64encode(image_bytes).decode("ascii")],
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0.4, "num_ctx": VISION_NUM_CTX,
                    "num_gpu": NUM_GPU, "num_predict": 120},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL + "/api/generate", data=payload,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    return (data.get("response", "") or "").strip()


def vision_ready():
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        names = [m.get("name", "") for m in data.get("models", [])]
        return any(n.startswith(VISION_MODEL) for n in names)
    except Exception:
        return False


def analyze_once():
    """Один кадр: захват -> vision-модель -> озвучка. Возвращает вердикт."""
    from core import tts
    img = _grab_screen()
    if img is None:
        return "Не смогла захватить экран. Проверь библиотеку mss."
    if not vision_ready():
        return f"Vision-модель {VISION_MODEL} не найдена. Скажи: ollama pull {VISION_MODEL}."
    try:
        verdict = _ask_llava(img, COACH_PROMPT)
    except Exception as e:
        return f"Тренер не смог проанализировать кадр: {e}"
    if verdict:
        tts.say(verdict)
    return verdict or "Кадр пустой, тренер молчит."


def _loop():
    from core import tts
    tts.say("Протокол Cyber-Coach запущен. Показывай свой билд, босс, я слежу за каткой.")
    while not _state["stop"].is_set():
        try:
            img = _grab_screen()
            if img and vision_ready():
                verdict = _ask_llava(img, COACH_PROMPT)
                if verdict:
                    _notify(verdict)
                    tts.say(verdict)
        except Exception:
            pass
        _state["stop"].wait(COACH_INTERVAL)


def start():
    with _lock:
        if _state["active"]:
            return "Протокол Cyber-Coach уже работает, босс."
        _state["stop"].clear()
        _state["active"] = True
        _state["thread"] = threading.Thread(target=_loop, daemon=True)
        _state["thread"].start()
    return "Протокол Cyber-Coach запущен. Показывай свой билд, босс, я слежу за каткой."


def stop():
    with _lock:
        if not _state["active"]:
            return "Тренер и так не активен."
        _state["stop"].set()
        _state["active"] = False
    return "Протокол Cyber-Coach остановлен. Отдыхай, босс, катка подождёт."


def coach_status():
    return ("Cyber-Coach: РАБОТАЕТ. " if _state["active"] else "Cyber-Coach: выкл. ") + \
        (f"Vision-модель {VISION_MODEL} на связи." if vision_ready()
         else f"Vision-модель {VISION_MODEL} недоступна.")


ACTIONS = {
    "game.coach_start": {"func": start, "desc": "Запустить Протокол Cyber-Coach (непрерывный анализ игры) "},
    "game.coach_stop": {"func": stop, "desc": "Остановить Протокол Cyber-Coach"},
    "game.coach_status": {"func": coach_status, "desc": "Статус Cyber-Coach"},
    "game.analyze_now": {"func": analyze_once, "desc": "Разовый анализ текущего кадра игры"},
}
