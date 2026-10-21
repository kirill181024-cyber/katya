import importlib.util
import sys
import threading
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

_ACTIONS = {}
_LOAD_ERRORS = {}


def load_all():
    _ACTIONS.clear()
    _LOAD_ERRORS.clear()
    if not SKILLS_DIR.exists():
        return
    for path in sorted(SKILLS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = "skills." + path.stem
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            actions = getattr(mod, "ACTIONS", None)
            if not isinstance(actions, dict):
                continue
            for name, meta in actions.items():
                _ACTIONS[name] = {
                    "func": meta.get("func"),
                    "desc": meta.get("desc", ""),
                    "params": meta.get("params", {}),
                    "skill": path.stem,
                    "async": bool(meta.get("async", False)),
                }
            if hasattr(mod, "init"):
                try:
                    mod.init()
                except Exception:
                    _LOAD_ERRORS[path.stem + ".init"] = traceback.format_exc()
        except Exception:
            _LOAD_ERRORS[path.stem] = traceback.format_exc()
            sys.modules.pop(mod_name, None)


def action_names():
    return sorted(_ACTIONS.keys())


def action_list_text():
    lines = []
    for name, meta in _ACTIONS.items():
        params = ", ".join(f"{k}: {v}" for k, v in meta["params"].items())
        tail = f" (параметры: {params})" if params else ""
        lines.append(f"- {name}: {meta['desc']}{tail}")
    return "\n".join(lines)


def load_errors():
    return dict(_LOAD_ERRORS)


def run(name, args=None):
    meta = _ACTIONS.get(name)
    if not meta or not meta["func"]:
        return f"[skills] неизвестное действие: {name}"
    args = args or {}
    if not isinstance(args, dict):
        args = {"value": args, "name": args, "task": args, "text": args,
                "url": args, "keyword": args, "percent": args}
    kwargs = {k: v for k, v in args.items()}
    try:
        result = meta["func"](**kwargs)
        return "" if result is None else str(result)
    except TypeError as e:
        return f"[skills] неверные аргументы для {name}: {e}"
    except Exception:
        return f"[skills] ошибка {name}: {traceback.format_exc(limit=3)}"


def run_async(name, args, on_done=None):
    def _worker():
        res = run(name, args)
        if on_done:
            on_done(res)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


def save_and_run_learned_skill(code_text, name="auto_learned", args=None,
                               heal=True, max_fix=2):
    """Сохраняет сгенерированный ИИ код в skills/ и динамически выполняет.

    Регистрирует его действия в загрузчике. При падении (traceback)
    пробует self-healing: просит мозг исправить код по логу ошибки.
    """
    from . import self_coder
    args = args or {}
    attempt = 0
    last_err = ""
    while attempt <= (max_fix if heal else 0):
        code = self_coder._extract_code(code_text)
        ok, err = self_coder._validate(code)
        if not ok:
            last_err = err
        else:
            path = self_coder.write_skill(code, name)
            try:
                mod, actions = self_coder.load_skill(path)
                added = self_coder.register_actions(actions, name)
                first = (added or list(actions.keys()))
                if not first:
                    return "Сгенерированный плагин не содержит действий."
                target = next((a for a in first if not a.startswith("self.")), first[0])
                if args:
                    result = run(target, args)
                else:
                    result = f"Плагин «{name}» загружен, действия: {', '.join(added)}."
                return result
            except Exception:
                last_err = traceback.format_exc()
                path.unlink(missing_ok=True)
        if not heal or attempt == max_fix:
            break
        attempt += 1
        try:
            from . import brain
            fix_prompt = (
                "Твой Python-плагин для агента Катя упал. Ниже лог ошибки. "
                "Верни ТОЛЬКО исправленный Python-файл (без markdown), "
                "с функциями и словарём ACTIONS в конце.\n\nЛОГ:\n" + last_err[-2000:])
            code_text = brain._api(
                [{"role": "user", "content": fix_prompt}],
                self_coder.CODE_PROMPT.replace("%TASK%", "исправь ошибку"), timeout=240)
        except Exception:
            break
    return f"Плагин не заработал после попыток. Последняя ошибка: {last_err[:300]}"
