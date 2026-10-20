import ast
import importlib.util
import re
import sys
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

CODE_PROMPT = """Ты — генератор Python-плагинов для агента Катя 2.0 (Windows).
Напиши РОВНО один Python-файл, без markdown, без пояснений, без ```.
Файл должен содержать:
1) одну или несколько функций, решающих задачу пользователя;
2) словарь ACTIONS в конце вида:
ACTIONS = {
  "action.name": {"func": имя_функции, "desc": "что делает", "params": {"arg": "описание"}},
}
Правила:
- Только стандартная библиотека, plus psutil/os/subprocess/requests при необходимости.
- Функции должны возвращать короткую строку-результат на русском.
- Не делай сетевых запросов к пиратским/нелегальным ресурсам.
- Никаких вызовов input(), никакого бесконечного кода на верхнем уровне.
- Код должен быть безопасным и обратимым там, где возможно.
Задача пользователя: %TASK%
"""

_BLOCKED = ("input(", "__import__", "os.system(", "eval(", "exec(", "compile(",
            "shutil.rmtree", "ctypes.windll.kernel32")


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _slug(task, idx):
    text = re.sub(r"[^a-zA-Zа-яА-ЯёЁ ]", "", (task or "").lower())
    text = "".join(_TRANSLIT.get(ch, ch) for ch in text)
    base = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return f"auto_{base[:24]}_{idx}" if base else f"auto_skill_{idx}"


def _extract_code(raw):
    if not raw:
        return ""
    text = raw.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text, flags=re.M).strip()
    m = re.search(r"(import |from |def |ACTIONS\s*=)", text)
    if m and m.start() > 0:
        text = text[m.start():]
    return text.strip()


def _validate(code):
    """Возвращает (ok, error). Проверяет синтаксис, наличие ACTIONS и безопасность."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"синтаксис: {e}"
    has_actions = any(
        isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ACTIONS" for t in n.targets)
        for n in tree.body)
    if not has_actions:
        return False, "нет словаря ACTIONS"
    for needle in _BLOCKED:
        if needle in code:
            return False, f"запрещённая конструкция: {needle}"
    if any(isinstance(n, ast.While) and isinstance(n.test, ast.Constant)
           and n.test.value is True for n in ast.walk(tree)):
        return False, "бесконечный цикл while True"
    return True, ""


def write_skill(code, name):
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    path = SKILLS_DIR / f"{name}.py"
    path.write_text(code, encoding="utf-8")
    return path


def load_skill(path):
    mod_name = "skills." + path.stem
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod, getattr(mod, "ACTIONS", {})


def register_actions(actions, skill_name):
    from . import skills_loader
    added = []
    for act_name, meta in actions.items():
        if not isinstance(meta, dict):
            continue
        skills_loader._ACTIONS[act_name] = {
            "func": meta.get("func"),
            "desc": meta.get("desc", ""),
            "params": meta.get("params", {}),
            "skill": skill_name,
            "async": bool(meta.get("async", False)),
        }
        added.append(act_name)
    return added


def generate(task, attempts=3):
    """Просит Ollama написать плагин, при ошибке просит исправить.
    Сохраняет, подхватывает и регистрирует действия."""
    from . import brain
    if not brain.available():
        return "Мозг офлайн — не могу писать новый код. Запусти Ollama."

    system = CODE_PROMPT.replace("%TASK%", task)
    messages = [{"role": "user", "content": task}]
    last_error = ""

    for attempt in range(1, attempts + 1):
        try:
            raw = brain._api(messages, system, timeout=240)
        except Exception as e:
            return f"Не смогла сгенерировать код: {e}"

        code = _extract_code(raw)
        ok, err = _validate(code)
        if not ok:
            last_error = err
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user",
                             "content": f"Код отклонён: {err}. Исправь и верни только Python-файл."})
            continue

        existing = {p.stem for p in SKILLS_DIR.glob("*.py")}
        idx = len(existing) + 1
        name = _slug(task, idx)
        while name in existing:
            idx += 1
            name = _slug(task, idx)

        path = write_skill(code, name)
        try:
            _mod, actions = load_skill(path)
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            path.unlink(missing_ok=True)
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user",
                             "content": f"При загрузке ошибка: {last_error}. "
                                        "Убедись, что все функции из ACTIONS определены. "
                                        "Верни только исправленный Python-файл."})
            continue

        if not actions:
            path.unlink(missing_ok=True)
            last_error = "нет действий"
            continue

        added = register_actions(actions, name)
        return (f"Научилась новому: создала плагин «{name}» с действиями "
                f"{', '.join(added)}. Готова применять.")

    return f"Не удалось создать рабочий плагин за {attempts} попытки. Последняя ошибка: {last_error}"


ACTIONS = {
    "self.code": {
        "func": generate,
        "desc": "Самообучение: написать новый Python-плагин под задачу, которой нет среди навыков",
        "params": {"task": "что должна уметь Катя"},
    },
}
