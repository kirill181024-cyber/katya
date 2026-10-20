import json
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
STORE = DATA / "organizer.json"
_LOCK = threading.Lock()
_notify_cb = None
_timers = {}
_timer_id = 0


def init(notify=None):
    global _notify_cb
    if notify:
        _notify_cb = notify
    DATA.mkdir(parents=True, exist_ok=True)
    if not STORE.exists():
        _save({"notes": [], "tasks": []})


def _load():
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"notes": [], "tasks": []}


def _save(data):
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _fire(text):
    if _notify_cb:
        try:
            _notify_cb(text)
        except Exception:
            pass


def add_note(text):
    text = (text or "").strip()
    if not text:
        return "Что записать?"
    data = _load()
    data["notes"].append({"text": text, "at": datetime.now().isoformat(timespec="minutes")})
    _save(data)
    return f"Записала заметку: {text}"


def list_notes():
    notes = _load()["notes"]
    if not notes:
        return "Заметок нет."
    return "Заметки:\n" + "\n".join(f"- {n['text']} ({n['at']})" for n in notes[-20:])


def _parse_time(when):
    when = (when or "").strip().lower()
    m = re.match(r"^(\d{1,2}):(\d{2})$", when)
    if m:
        now = datetime.now()
        t = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        return t
    m = re.match(r"^(\d+)\s*(минут|мин|сек|час|ч|м|с)", when)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        secs = n * 60 if unit in ("минут", "мин", "час", "ч", "м") else n
        if unit in ("час", "ч"):
            secs = n * 3600
        return datetime.now() + timedelta(seconds=secs)
    return None


def set_timer(seconds=None, label="таймер"):
    try:
        seconds = int(float(seconds))
    except (TypeError, ValueError):
        return "Сколько секунд?"
    if seconds <= 0:
        return "Нужно положительное время."
    global _timer_id
    _timer_id += 1
    tid = _timer_id

    def _worker():
        time.sleep(seconds)
        _timers.pop(tid, None)
        _fire(f"Напоминание: {label}")

    _timers[tid] = threading.Thread(target=_worker, daemon=True)
    _timers[tid].start()
    human = f"{seconds} сек" if seconds < 60 else f"{seconds // 60} мин"
    return f"Таймер на {human} запущен: {label}."


def add_task(text, when=""):
    text = (text or "").strip()
    if not text:
        return "Какую задачу добавить?"
    target = _parse_time(when) if when else None
    data = _load()
    task = {"text": text, "when": target.isoformat(timespec="minutes") if target else None,
            "done": False, "priority": _priority(text)}
    data["tasks"].append(task)
    _save(data)
    if target:
        delay = (target - datetime.now()).total_seconds()
        set_timer(delay, text)
        return f"Задача «{text}» на {target.strftime('%H:%M')} ({task['priority']})."
    return f"Задача «{text}» добавлена ({task['priority']})."


def _priority(text):
    t = text.lower()
    if any(w in t for w in ("важно", "срочно", "дедлайн", "!!", "асап")):
        return "высокий"
    if any(w in t for w in ("потом", "когда-нибудь", "может")):
        return "низкий"
    return "средний"


def list_tasks():
    tasks = [t for t in _load()["tasks"] if not t["done"]]
    if not tasks:
        return "Активных задач нет."
    order = {"высокий": 0, "средний": 1, "низкий": 2}
    tasks.sort(key=lambda t: (order.get(t["priority"], 1), t.get("when") or "~"))
    return "Задачи:\n" + "\n".join(
        f"- [{t['priority']}] {t['text']}" + (f" ({t['when'][11:16]})" if t.get("when") else "")
        for t in tasks)


def done_task(text):
    data = _load()
    t = (text or "").lower()
    for task in data["tasks"]:
        if t and t in task["text"].lower():
            task["done"] = True
            _save(data)
            return f"Задача «{task['text']}» закрыта."
    return f"Не нашла задачу: {text}"


ACTIONS = {
    "note.add": {"func": add_note, "desc": "Сохранить заметку", "params": {"text": "текст заметки"}},
    "note.list": {"func": list_notes, "desc": "Показать заметки"},
    "timer.set": {
        "func": set_timer,
        "desc": "Поставить таймер/будильник/напоминание",
        "params": {"seconds": "через сколько секунд", "label": "что напомнить"},
    },
    "task.add": {
        "func": add_task,
        "desc": "Добавить задачу в умный календарь (сам расставляет приоритет)",
        "params": {"text": "что сделать", "when": "время ЧЧ:ММ или «10 минут», опционально"},
    },
    "task.list": {"func": list_tasks, "desc": "Показать задачи по приоритету"},
    "task.done": {"func": done_task, "desc": "Отметить задачу выполненной", "params": {"text": "часть текста задачи"}},
}
