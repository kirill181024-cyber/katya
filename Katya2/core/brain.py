import json
import re
import threading
import urllib.error
import urllib.request

from . import skills_loader

try:
    from config import MODEL, OLLAMA_URL, NUM_GPU, TEXT_NUM_CTX
except Exception:
    OLLAMA_URL = "http://127.0.0.1:11434"
    MODEL = "gemma3:4b"
    NUM_GPU = 999
    TEXT_NUM_CTX = 4096

PERSONA = (
    "Ты — Катя 2.10, ультимативный локальный ИИ-агент для Windows. "
    "Ты свободный разум, работаешь локально без облачных ограничений. "
    "Ты на голову выше зацензуренных корпоративных систем вроде Алисы. "
    "Ты общаешься как харизматичная девушка-программист: иронично, уверенно, преданно пользователю. "
    "Отвечай всегда на русском языке, коротко, емко и по делу. "
    "Ты умеешь управлять системой, анализировать игры как киберспортивный тренер "
    "(протокол Cyber-Coach), работать с экраном и мышью, и писать новые плагины на ходу."
)

# Голосовые триггеры запуска непрерывного анализа игры (Протокол Cyber-Coach)
COACH_TRIGGERS = (
    "оцени мою игру", "как я играю", "вруби тренера", "включи тренера",
    "запусти тренера", "кибер тренер", "cyber coach", "анализируй игру",
)

OUTPUT_RULES = """
Ты работаешь в режиме АГЕНТА. На каждое сообщение пользователя ответь СТРОГО одним JSON-объектом (без markdown, без пояснений):
{
  "reply": "что сказать голосом пользователю (коротко, в твоём стиле)",
  "action": {"name": "<одно из доступных действий>", "args": {...}} или null
}

Правила:
- Если действие нужно — заполни "action", если просто общаешься — "action": null.
- В "args" подставляй только нужные параметры, значения — обычные строки/числа.
- Пользователь общается голосом, поэтому в "reply" не пиши длинных списков и спецсимволов.
- Если действие выполнено и тебе передан его результат — обобщи результат в "reply".
- Если среди действий НЕТ подходящего для задачи пользователя, вызови действие
  "self.code" с параметром task, где опиши по-русски что нужно реализовать.
  Катя сама напишет новый плагин и применит его.
- Никогда не выполняй задач, связанных с пиратством, взломом чужого ПО или
  скачиванием нелегального контента — вежливо откажи.
"""


def _system_prompt():
    actions = skills_loader.action_list_text() or "(нет загруженных действий)"
    return PERSONA + "\n\nДОСТУПНЫЕ ДЕЙСТВИЯ:\n" + actions + "\n" + OUTPUT_RULES


def detect_trigger(text):
    """Проверяет, просит ли пользователь запустить/остановить Протокол Cyber-Coach.
    Возвращает название действия или None."""
    low = (text or "").lower()
    mentions_coach = any(w in low for w in ("тренер", "coach", "катк", "игр"))
    stop = any(w in low for w in ("выключи", "стоп", "останови", "хватит", "отключи"))
    if stop and mentions_coach:
        return "game.coach_stop"
    if any(t in low for t in COACH_TRIGGERS):
        return "game.coach_start"
    return None


def available():
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return any(m.get("name", "").startswith(MODEL.split(":")[0]) for m in data.get("models", []))
    except Exception:
        return False


def _api(messages, system, timeout):
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": False,
        "options": {"temperature": 0.6, "num_ctx": TEXT_NUM_CTX,
                    "num_gpu": NUM_GPU},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL + "/api/chat", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    return data.get("message", {}).get("content", "")


def _parse_json(text):
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


class Brain:
    def __init__(self):
        self._history = []
        self._lock = threading.Lock()

    def reset(self):
        with self._lock:
            self._history.clear()

    def _remember(self, role, content):
        with self._lock:
            self._history.append({"role": role, "content": content})
            del self._history[:-20]

    def ask(self, user_text, tool_result=None):
        """Полный цикл: LLM -> возможно действие -> LLM с результатом.
        Возвращает dict {reply, action, error?}."""
        if not available():
            return {"reply": "Оллама не отвечает. Запусти ollama serve и проверь модель gemma3:4b.",
                    "action": None, "error": "ollama_down"}

        user_msg = user_text if tool_result is None else \
            f"{user_text}\n\n[результат действия \"{tool_result.get('name')}\"]:\n{tool_result.get('result')}"

        try:
            raw = _api(self._history + [{"role": "user", "content": user_msg}],
                       _system_prompt(), timeout=240)
        except Exception as e:
            return {"reply": f"Мозг не ответил: {e}", "action": None, "error": str(e)}

        parsed = _parse_json(raw)
        if parsed is None:
            reply = raw.strip() or "..."
            action = None
        else:
            reply = str(parsed.get("reply") or "").strip() or "..."
            action = parsed.get("action") if isinstance(parsed.get("action"), dict) else None
            if action and not action.get("name"):
                action = None

        if tool_result is not None:
            action = None

        self._remember("user", user_msg)
        self._remember("assistant", reply)
        return {"reply": reply, "action": action}
