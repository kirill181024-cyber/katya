"""Vision OCR — скриншот экрана, распознавание текста, анализ через Ollama.

Распознаёт текст со всего экрана или из заданной области, умеет
отправлять распознанный текст (например, ошибку в коде) в текстовую
модель Ollama для разбора и совета.
"""

import base64
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

from config import MODEL, OLLAMA_URL

_SHOTS = Path(os.path.expanduser("~")) / "Pictures"
_SHOTS.mkdir(parents=True, exist_ok=True)


def _grab(region=None):
    """Скриншот. region = (left, top, width, height) или None (весь экран)."""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=region, all_screens=True)
        return img
    except Exception:
        pass
    try:
        import mss
        from PIL import Image
        with mss.mss() as sct:
            mon = sct.monitors[1]
            shot = sct.grab(mon)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    except Exception as e:
        raise RuntimeError(f"захват экрана недоступен: {e}")


def take_screenshot(region=None):
    try:
        img = _grab(_region_tuple(region))
        out = _SHOTS / f"katya_ocr_{datetime.now():%Y%m%d_%H%M%S}.png"
        img.save(out)
        return f"Скриншот сохранён: {out}"
    except Exception as e:
        return f"Скриншот не удался: {e}"


def _region_tuple(region):
    if not region:
        return None
    if isinstance(region, str):
        try:
            region = json.loads(region)
        except Exception:
            region = [int(x) for x in region.replace(",", " ").split()]
    if isinstance(region, (list, tuple)) and len(region) == 4:
        return tuple(int(v) for v in region)
    return None


def _ocr_text(img):
    """Пытается распознать текст: сначала pytesseract, потом vision llava."""
    try:
        import pytesseract
        return pytesseract.image_to_string(img, lang="rus+eng").strip()
    except Exception:
        pass
    return None


def _vision_ask(image_bytes, prompt):
    vmodel = "llava"
    payload = json.dumps({
        "model": vmodel,
        "prompt": prompt,
        "images": [base64.b64encode(image_bytes).decode("ascii")],
        "stream": False,
        "keep_alive": "30m",
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL + "/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode("utf-8", "replace")) \
            .get("response", "").strip()


def _text_ask(text, prompt):
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt + "\n\n" + text}],
        "stream": False,
        "options": {"temperature": 0.4},
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL + "/api/chat", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8", "replace")) \
            .get("message", {}).get("content", "").strip()


def read_screen(region=None):
    """Прочитать текст с экрана (OCR)."""
    try:
        img = _grab(_region_tuple(region))
    except Exception as e:
        return str(e)
    text = _ocr_text(img)
    if text:
        return "Распознанный текст:\n" + text[:1500]
    return ("OCR-движок (Tesseract) не найден. Могу использовать vision-модель: "
            "вызови vision.analyze.")


def analyze_errors(region=None):
    """Найти и разобрать ошибку в коде с экрана."""
    try:
        img = _grab(_region_tuple(region))
    except Exception as e:
        return str(e)
    text = _ocr_text(img)
    prompt = ("Ты — опытный программист. Ниже текст с экрана пользователя, "
              "скорее всего ошибка/трейсбек. Объясни по-русски причину и дай "
              "короткое решение. Если это не ошибка — скажи что видишь.")
    try:
        if text:
            return _text_ask(text[:3000], prompt)
        import io
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        return _vision_ask(buf.getvalue(),
                           "Посмотри на экран, найди ошибку/трейсбек в коде "
                           "или проблему и объясни по-русски, как исправить.")
    except Exception as e:
        return f"Анализ не удался: {e}"


def analyze_screen(question=""):
    """Отправить скриншот в vision-модель с произвольным вопросом."""
    try:
        img = _grab()
        import io
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        q = question or "Опиши подробно, что происходит на экране, по-русски."
        return _vision_ask(buf.getvalue(), q)
    except Exception as e:
        return f"Vision-анализ не удался: {e}"


ACTIONS = {
    "vision.screenshot": {"func": take_screenshot, "desc": "Сделать скриншот экрана",
                          "params": {"region": "область left,top,w,h (опционально)"}},
    "vision.ocr": {"func": read_screen, "desc": "Распознать текст с экрана (OCR)",
                   "params": {"region": "область left,top,w,h (опционально)"}},
    "vision.analyze": {"func": analyze_screen, "desc": "Vision-анализ экрана моделью llava",
                       "params": {"question": "что спросить про экран"}},
    "vision.errors": {"func": analyze_errors, "desc": "Найти ошибку в коде на экране и объяснить",
                      "params": {"region": "область left,top,w,h (опционально)"}},
}
