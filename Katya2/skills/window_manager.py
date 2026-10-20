import subprocess

import pygetwindow as gw


def _screen():
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        return 1920, 1080


SCREEN_W, SCREEN_H = _screen()
HALF_W = SCREEN_W // 2


def _visible_windows():
    out = []
    for w in gw.getAllWindows():
        try:
            if w.title and w.isVisible and not w.isMinimized:
                out.append(w)
        except Exception:
            continue
    return out


def _find(keyword):
    kw = (keyword or "").strip().lower()
    if not kw:
        return None
    for w in gw.getAllWindows():
        try:
            if kw in w.title.lower():
                return w
        except Exception:
            continue
    return None


def list_windows():
    wins = _visible_windows()
    if not wins:
        return "Открытых окон нет."
    return "Окна:\n" + "\n".join(f"- {w.title[:80]}" for w in wins[:25])


def split_windows(left_kw="browser", right_kw="code"):
    lw, rw = _find(left_kw), _find(right_kw)
    if not lw:
        return f"Не нашла окно: {left_kw}"
    if not rw:
        return f"Не нашла окно: {right_kw}"
    for w in (lw, rw):
        try:
            if w.isMinimized:
                w.restore()
        except Exception:
            pass
    try:
        lw.moveTo(0, 0)
        lw.resizeTo(HALF_W, SCREEN_H)
        rw.moveTo(HALF_W, 0)
        rw.resizeTo(SCREEN_W - HALF_W, SCREEN_H)
    except Exception as e:
        return f"Не получилось расставить окна: {e}"
    return f"Склеила: «{lw.title[:40]}» слева, «{rw.title[:40]}» справа."


def hide_except(keyword=""):
    kw = (keyword or "").strip().lower()
    hidden = 0
    for w in _visible_windows():
        try:
            if kw and kw in w.title.lower():
                continue
            w.minimize()
            hidden += 1
        except Exception:
            continue
    if not kw:
        return f"Скрыла все окна ({hidden}). Рабочий стол чист."
    return f"Скрыла окна ({hidden}), оставила только «{keyword}»."


def show_all():
    n = 0
    for w in gw.getAllWindows():
        try:
            if w.title and w.isMinimized:
                w.restore()
                n += 1
        except Exception:
            continue
    return f"Развернула окна: {n}."


def focus_window(keyword):
    w = _find(keyword)
    if not w:
        return f"Окно не найдено: {keyword}"
    try:
        if w.isMinimized:
            w.restore()
        w.activate()
        return f"Фокус на «{w.title[:60]}»."
    except Exception as e:
        return f"Не смогла вывести окно: {e}"


def close_window(keyword):
    w = _find(keyword)
    if not w:
        return f"Окно не найдено: {keyword}"
    title = w.title
    try:
        w.close()
        return f"Закрыла «{title[:60]}»."
    except Exception:
        return f"Не получилось закрыть «{title[:40]}», попробуй taskkill."


def kill_frozen(image):
    image = (image or "").strip()
    if not image:
        return "Нужно имя процесса, например chrome.exe"
    if not image.lower().endswith(".exe"):
        image += ".exe"
    r = subprocess.run(["taskkill", "/F", "/IM", image],
                       capture_output=True, text=True, creationflags=0x08000000)
    if r.returncode == 0:
        return f"Процесс {image} убит."
    return f"{image}: {(r.stderr or r.stdout).strip()[:200]}"


ACTIONS = {
    "window.list": {"func": list_windows, "desc": "Список открытых окон"},
    "window.split": {
        "func": split_windows,
        "desc": "Расположить два окна слева/справа (склей окна)",
        "params": {"left_kw": "название левого окна", "right_kw": "название правого окна"},
    },
    "window.hide_except": {
        "func": hide_except,
        "desc": "Свернуть все окна кроме указанного (спрячь всё/спрячь стрим)",
        "params": {"keyword": "окно, которое оставить; пусто = скрыть всё"},
    },
    "window.show_all": {"func": show_all, "desc": "Развернуть все свёрнутые окна"},
    "window.focus": {
        "func": focus_window,
        "desc": "Вывести окно на передний план",
        "params": {"keyword": "название окна"},
    },
    "window.close": {
        "func": close_window,
        "desc": "Закрыть окно по названию",
        "params": {"keyword": "название окна"},
    },
    "process.kill": {
        "func": kill_frozen,
        "desc": "Принудительно убить зависший процесс (taskkill /F)",
        "params": {"image": "имя процесса, например chrome.exe"},
    },
}
