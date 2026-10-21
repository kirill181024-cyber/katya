"""Протоколы «Marvel».

- «Максимальный Overclock»: высокая производительность Windows, очистка ОЗУ,
  снижение фонового приоритета софта (буст FPS в играх).
- «Спрячь палево»: свернуть все окна, полностью замьютить звук, заблокировать экран.
"""

import ctypes
import subprocess
import time

import psutil

LOW_PRIORITY = ("chrome", "discord", "telegram", "spotify", "slack", "msedge",
                "firefox", "teams", "code", "electron", "whatsapp", "vk",
                "battle.net", "epicgameslauncher", "uplay", "steam", "obs")

_POWER_HIGH = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
_POWER_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
_NO_WINDOW = 0x08000000

_saved_prios = {}
_active = False


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, creationflags=_NO_WINDOW)


def _set_scheme(guid):
    return _run(["powercfg", "/setactive", guid])


def _volume_endpoint():
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetSpeakers().EndpointVolume


def overclock():
    """Протокол «Максимальный Overclock»."""
    global _active
    lowered = 0
    for p in psutil.process_iter(["pid", "name", "nice"]):
        try:
            name = (p.info["name"] or "").lower().replace(".exe", "")
            if any(name == n or name.startswith(n) for n in LOW_PRIORITY):
                _saved_prios[p.pid] = p.info["nice"]
                p.nice(psutil.IDLE_PRIORITY_CLASS)
                lowered += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    _set_scheme(_POWER_HIGH)
    freed = purge_memory()
    _active = True
    return (f"Протокол «Максимальный Overclock» активен: {lowered} фоновых "
            f"процессов приоритет понижен, питание на максимум. {freed}")


def overclock_off():
    global _active
    restored = 0
    for pid, prio in list(_saved_prios.items()):
        try:
            psutil.Process(pid).nice(prio)
            restored += 1
        except Exception:
            pass
    _saved_prios.clear()
    _set_scheme(_POWER_BALANCED)
    _active = False
    return f"Overclock выключен: {restored} процессов восстановлено, питание сбалансировано."


def purge_memory():
    before = psutil.virtual_memory().available
    n = 0
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["name"] in ("System", "Idle", "Registry", ""):
                continue
            ctypes.windll.psapi.EmptyWorkingSet(psutil.Process(p.info["pid"])._handle)
            n += 1
        except Exception:
            continue
    time.sleep(0.4)
    after = psutil.virtual_memory().available
    return f"ОЗУ: освобождено ~{max(0, (after - before) // (1024 * 1024))} МБ ({n} процессов)."


def hide_all():
    """Протокол «Спрячь палево»: свернуть окна, мут звука, блокировка экрана."""
    results = []
    try:
        ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)   # LWin down
        ctypes.windll.user32.keybd_event(0x44, 0, 0, 0)   # D down
        ctypes.windll.user32.keybd_event(0x44, 0, 2, 0)   # D up
        ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)   # LWin up
        results.append("окна свёрнуты (Show Desktop)")
    except Exception as e:
        results.append(f"сворачивание не удалось: {e}")
    try:
        _volume_endpoint().SetMute(1, None)
        results.append("звук выключен")
    except Exception as e:
        results.append(f"мут не удался: {e}")
    time.sleep(0.4)
    try:
        ctypes.windll.user32.LockWorkStation()
        results.append("экран заблокирован")
    except Exception as e:
        results.append(f"блокировка не удалась: {e}")
    return "Протокол «Спрячь палево»: " + ", ".join(results) + "."


def unmute():
    try:
        _volume_endpoint().SetMute(0, None)
        return "Звук возвращён."
    except Exception as e:
        return f"Не смогла вернуть звук: {e}"


def status():
    vm = psutil.virtual_memory()
    return ("Overclock: ВКЛ. " if _active else "Overclock: выкл. ") + \
        f"RAM свободно {vm.percent}% ({vm.available // (1024 ** 2)} МБ)."


ACTIONS = {
    "marvel.overclock": {"func": overclock, "desc": "Протокол «Максимальный Overclock»: буст FPS, очистка ОЗУ, приоритеты"},
    "marvel.overclock_off": {"func": overclock_off, "desc": "Выключить Overclock"},
    "marvel.purge": {"func": purge_memory, "desc": "Очистить оперативную память"},
    "marvel.hide": {"func": hide_all, "desc": "Протокол «Спрячь палево»: свернуть окна, мут звука, блокировка экрана"},
    "marvel.unmute": {"func": unmute, "desc": "Вернуть звук после «Спрячь палево»"},
    "marvel.status": {"func": status, "desc": "Статус Overclock и ОЗУ"},
}
