"""Computer Use — управление мышью и клавиатурой через pyautogui.

Клик по координатам, ввод текста, горячие клавиши и выполнение
цепочки действий, описанной списком шагов.
"""

import time

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
except Exception:
    pyautogui = None


def _require():
    if pyautogui is None:
        return "pyautogui не установлен. Выполни pip install pyautogui."
    return None


def click(x, y, button="left", double=False):
    err = _require()
    if err:
        return err
    try:
        x, y = int(x), int(y)
        if str(double).lower() in ("1", "true", "да"):
            pyautogui.doubleClick(x, y, button=button)
        else:
            pyautogui.click(x, y, button=button)
        return f"Кликнула ({x}, {y}) кнопкой {button}."
    except Exception as e:
        return f"Клик не удался: {e}"


def type_text(text):
    err = _require()
    if err:
        return err
    try:
        pyautogui.typewrite(str(text), interval=0.02)
        return "Текст введён."
    except Exception as e:
        return f"Не смогла ввести текст: {e}"


def hotkey(keys):
    err = _require()
    if err:
        return err
    try:
        if isinstance(keys, str):
            combo = [k.strip().lower() for k in keys.replace("+", " ").split() if k.strip()]
        else:
            combo = [str(k).lower() for k in keys]
        if not combo:
            return "Какие клавиши нажать?"
        pyautogui.hotkey(*combo)
        return f"Нажала: {'+'.join(combo)}."
    except Exception as e:
        return f"Не смогла нажать клавиши: {e}"


def press(key):
    err = _require()
    if err:
        return err
    try:
        pyautogui.press(str(key).lower())
        return f"Нажала {key}."
    except Exception as e:
        return f"Не смогла нажать {key}: {e}"


def sequence(steps):
    """Выполнить цепочку шагов.

    steps: список строк вида:
      "click 640 360", "double 640 360", "move 100 100",
      "type привет мир", "hotkey ctrl+c", "press enter", "wait 0.5"
    """
    err = _require()
    if err:
        return err
    if isinstance(steps, str):
        import json
        try:
            steps = json.loads(steps)
        except Exception:
            steps = [s for s in steps.split(";") if s.strip()]
    done = []
    for raw in steps or []:
        raw = str(raw).strip()
        if not raw:
            continue
        parts = raw.split()
        cmd = parts[0].lower()
        try:
            if cmd in ("click", "double", "move") and len(parts) >= 3:
                x, y = int(parts[1]), int(parts[2])
                if cmd == "move":
                    pyautogui.moveTo(x, y, duration=0.2)
                elif cmd == "double":
                    pyautogui.doubleClick(x, y)
                else:
                    pyautogui.click(x, y)
                done.append(cmd)
            elif cmd == "type" and len(parts) >= 2:
                pyautogui.typewrite(raw.split(" ", 1)[1], interval=0.02)
                done.append("type")
            elif cmd == "hotkey" and len(parts) >= 2:
                combo = [k.strip().lower() for k in raw.split(" ", 1)[1].replace("+", " ").split()]
                pyautogui.hotkey(*combo)
                done.append("hotkey(" + "+".join(combo) + ")")
            elif cmd == "press" and len(parts) >= 2:
                pyautogui.press(parts[1].lower())
                done.append("press " + parts[1])
            elif cmd == "wait" and len(parts) >= 2:
                time.sleep(float(parts[1]))
                done.append("wait")
        except Exception as e:
            return f"Шаг «{raw}» сорвался: {e}. Выполнено: {done}"
    return f"Цепочка выполнена: {done}" if done else "Пустая цепочка действий."


def position():
    err = _require()
    if err:
        return err
    try:
        x, y = pyautogui.position()
        return f"Курсор в ({x}, {y})."
    except Exception as e:
        return f"Не смогла получить позицию: {e}"


def screenshot(path=None):
    err = _require()
    if err:
        return err
    try:
        import os
        from pathlib import Path
        from datetime import datetime
        if not path:
            out = Path(os.path.expanduser("~")) / "Pictures" / \
                f"katya_shot_{datetime.now():%Y%m%d_%H%M%S}.png"
            path = str(out)
        pyautogui.screenshot(path)
        return f"Скриншот сохранён: {path}"
    except Exception as e:
        return f"Скриншот не удался: {e}"


ACTIONS = {
    "pc.click": {"func": click, "desc": "Клик мышью по координатам экрана",
                 "params": {"x": "координата X", "y": "координата Y",
                            "button": "left/right", "double": "true для двойного"}},
    "pc.type": {"func": type_text, "desc": "Ввести текст с клавиатуры",
                "params": {"text": "текст"}},
    "pc.hotkey": {"func": hotkey, "desc": "Нажать горячие клавиши, напр. ctrl+c",
                  "params": {"keys": "комбинация клавиш"}},
    "pc.press": {"func": press, "desc": "Нажать одну клавишу",
                 "params": {"key": "клавиша"}},
    "pc.sequence": {"func": sequence, "desc": "Выполнить цепочку действий клик/ввод/клавиши",
                    "params": {"steps": "список шагов через ; или JSON"}},
    "pc.position": {"func": position, "desc": "Показать позицию курсора"},
    "pc.screenshot": {"func": screenshot, "desc": "Сделать скриншот экрана",
                      "params": {"path": "куда сохранить (опционально)"}},
}
