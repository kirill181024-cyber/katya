import os
import subprocess
import time

import psutil

LOW_PRIORITY = ("chrome", "discord", "telegram", "spotify", "slack", "msedge",
                "firefox", "teams", "code", "electron", "whatsapp", "vk")
_POWER_MIN = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
_POWER_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"

_saved_prios = {}
_boosted = False


def _set_scheme(guid):
    subprocess.run(["powercfg", "/setactive", guid],
                   capture_output=True, creationflags=0x08000000)


def boost_on():
    global _boosted
    lowered = 0
    for p in psutil.process_iter(["name", "nice"]):
        try:
            name = (p.info["name"] or "").lower().replace(".exe", "")
            if any(name == n or name.startswith(n) for n in LOW_PRIORITY):
                _saved_prios[p.pid] = p.info["nice"]
                p.nice(psutil.IDLE_PRIORITY_CLASS)
                lowered += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    _set_scheme(_POWER_MIN)
    _boosted = True
    return f"Overclock: {lowered} фоновых процессов понижено, схема питания — максимальная производительность."


def boost_off():
    global _boosted
    restored = 0
    for pid, prio in list(_saved_prios.items()):
        try:
            p = psutil.Process(pid)
            p.nice(prio)
            restored += 1
        except Exception:
            pass
    _saved_prios.clear()
    _set_scheme(_POWER_BALANCED)
    _boosted = False
    return f"Режим снят: {restored} процессов восстановлено, схема питания — сбалансированная."


def clear_ram():
    import ctypes
    before = psutil.virtual_memory().available
    freed_proc = 0
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["name"] in ("System", "Idle", "Registry"):
                continue
            handle = psutil.Process(p.info["pid"])._handle
            ctypes.windll.psapi.EmptyWorkingSet(handle)
            freed_proc += 1
        except Exception:
            continue
    time.sleep(0.4)
    after = psutil.virtual_memory().available
    freed_mb = max(0, (after - before) // (1024 * 1024))
    return f"ОЗУ очищено у {freed_proc} процессов, освобождено ~{freed_mb} МБ."


def get_status():
    vm = psutil.virtual_memory()
    return ("Перегрузка: ВКЛ" if _boosted else "Перегрузка: выкл") + \
        f". RAM свободно {vm.percent}% ({vm.available // (1024**2)} МБ)."


def open_game(name):
    exe = (name or "").strip()
    if not exe:
        return "Какую игру запускать?"
    if exe.lower().startswith(("steam://", "http://", "https://")):
        os.startfile(exe)
        return f"Запускаю: {exe}"
    for cand in (exe, exe + ".exe"):
        try:
            os.startfile(cand)
            return f"Запускаю {cand}"
        except OSError:
            continue
    safe = exe.replace("'", "").replace("*", "")
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"$a = Get-StartApps | Where-Object Name -like '*{safe}*' | Select-Object -First 1; "
                        "if ($a) { Start-Process explorer.exe -ArgumentList \"shell:AppsFolder\\$($a.AppID)\"; 'OK' } else { 'NOTFOUND' }"],
                       capture_output=True, text=True, creationflags=0x08000000)
    if "OK" in (r.stdout or ""):
        return f"Запускаю «{exe}» через меню «Пуск»."
    return f"Не нашла «{exe}» в установленных программах."


ACTIONS = {
    "game.boost_on": {
        "func": boost_on,
        "desc": "Игровой режим Overclock: понизить приоритет фоновых процессов, максимум производительности",
    },
    "game.boost_off": {"func": boost_off, "desc": "Выключить игровой режим, вернуть всё как было"},
    "system.clear_ram": {"func": clear_ram, "desc": "Очистить оперативную память (EmptyWorkingSet)"},
    "system.status": {"func": get_status, "desc": "Статус системы: RAM, режим перегрузки"},
    "game.open": {
        "func": open_game,
        "desc": "Запустить игру/приложение по имени или steam://-ссылке",
        "params": {"name": "название игры или steam://rungameid/<id>"},
    },
}
