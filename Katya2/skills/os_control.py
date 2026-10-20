import os
import subprocess
import threading
import time

import psutil

LOW_PRIORITY = ("chrome", "discord", "telegram", "spotify", "slack", "msedge",
                "firefox", "teams", "code", "electron", "whatsapp", "vk",
                "battle.net", "epicgameslauncher", "uplay")

_POWER_MIN = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
_POWER_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"

NO_WINDOW = 0x08000000
_saved_prios = {}
_boosted = False
_cancel = threading.Event()


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, creationflags=NO_WINDOW)


def _set_scheme(guid):
    _run(["powercfg", "/setactive", guid])


def open_app(name):
    name = (name or "").strip()
    if not name:
        return "Что открыть?"
    low = name.lower()
    if low.startswith(("steam://", "http://", "https://")):
        os.startfile(name)
        return f"Открываю: {name}"
    for cand in (name, name + ".exe"):
        try:
            os.startfile(cand)
            return f"Запускаю {cand}."
        except OSError:
            continue
    safe = name.replace("'", "").replace("*", "")
    r = _run(["powershell", "-NoProfile", "-Command",
              f"$a = Get-StartApps | Where-Object Name -like '*{safe}*' | Select-Object -First 1; "
              "if ($a) { Start-Process explorer.exe -ArgumentList \"shell:AppsFolder\\$($a.AppID)\"; 'OK' } else { 'NO' }"])
    if "OK" in (r.stdout or ""):
        return f"Запускаю «{name}» через меню «Пуск»."
    return f"Не нашла «{name}»."


def kill_app(name):
    name = (name or "").strip()
    if not name:
        return "Какой процесс убить?"
    image = name if name.lower().endswith(".exe") else name + ".exe"
    r = _run(["taskkill", "/F", "/IM", image])
    if r.returncode == 0:
        return f"Процесс {image} убит."
    killed = 0
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if name.lower().replace(".exe", "") in (p.info["name"] or "").lower():
                p.kill()
                killed += 1
        except Exception:
            continue
    if killed:
        return f"Убила {killed} процесс(ов) по имени «{name}»."
    return f"Не нашла процесс «{name}»."


# ---------------------------------------------------------------- volume
def _endpoint():
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetSpeakers().EndpointVolume


def volume_set(percent):
    try:
        percent = max(0, min(100, int(percent)))
        _endpoint().SetMasterVolumeLevelScalar(percent / 100.0, None)
        return f"Громкость {percent}%."
    except Exception as e:
        return f"Не смогла изменить громкость: {e}"


def volume_mute(mute=True):
    try:
        on = str(mute).lower() in ("1", "true", "да", "вкл", "on")
        _endpoint().SetMute(1 if on else 0, None)
        return "Звук выключен." if on else "Звук включён."
    except Exception as e:
        return f"Не смогла переключить звук: {e}"


# --------------------------------------------------------------- brightness
def brightness_set(percent):
    try:
        import screen_brightness_control as sbc
        p = max(0, min(100, int(percent)))
        sbc.set_brightness(p)
        return f"Яркость {p}%."
    except Exception as e:
        return f"Не смогла изменить яркость: {e}"


# ------------------------------------------------------------------- trash
def empty_trash():
    try:
        import ctypes
        res = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7)
        return "Корзина очищена." if res == 0 else "Корзина уже пуста."
    except Exception as e:
        return f"Не смогла очистить корзину: {e}"


# ------------------------------------------------------------------- power
def lock_pc():
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return "Блокирую экран."
    except Exception as e:
        return f"Не смогла заблокировать: {e}"


def shutdown_pc(delay=10, restart=False):
    args = ["shutdown", "/r" if restart else "/s", "/t", str(int(delay))]
    r = _run(args)
    if r.returncode == 0:
        verb = "Перезагрузка" if restart else "Выключение"
        return f"{verb} через {int(delay)} сек. Скажи «отмени», чтобы остановить."
    return (r.stderr or "Не смогла выполнить выключение.").strip()[:200]


def cancel_power():
    r = _run(["shutdown", "/a"])
    return "Отменила выключение." if r.returncode == 0 else "Нечего отменять."


# ------------------------------------------------------- game mode (OC)
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
    freed = clear_ram()
    return f"Игровой режим Overclock: {lowered} процессов понижено, питание на максимум. {freed}"


def boost_off():
    global _boosted
    restored = 0
    for pid, prio in list(_saved_prios.items()):
        try:
            psutil.Process(pid).nice(prio)
            restored += 1
        except Exception:
            pass
    _saved_prios.clear()
    _set_scheme(_POWER_BALANCED)
    _boosted = False
    return f"Режим снят: {restored} процессов восстановлено, питание сбалансировано."


def clear_ram():
    import ctypes
    before = psutil.virtual_memory().available
    n = 0
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["name"] in ("System", "Idle", "Registry", ""):
                continue
            handle = psutil.Process(p.info["pid"])._handle
            ctypes.windll.psapi.EmptyWorkingSet(handle)
            n += 1
        except Exception:
            continue
    time.sleep(0.4)
    after = psutil.virtual_memory().available
    return f"ОЗУ: освобождено ~{max(0, (after - before) // (1024 * 1024))} МБ."


def system_status():
    vm = psutil.virtual_memory()
    return ("Overclock: ВКЛ. " if _boosted else "Overclock: выкл. ") + \
        f"RAM свободно {vm.percent}% ({vm.available // (1024 ** 2)} МБ)."


ACTIONS = {
    "os.open": {"func": open_app, "desc": "Открыть приложение/ссылку по имени",
                "params": {"name": "имя приложения или ссылка"}},
    "os.kill": {"func": kill_app, "desc": "Жёстко закрыть приложение (taskkill /F)",
                "params": {"name": "имя процесса или приложения"}},
    "os.volume_set": {"func": volume_set, "desc": "Установить громкость 0-100",
                      "params": {"percent": "громкость"}},
    "os.volume_mute": {"func": volume_mute, "desc": "Выключить/включить звук",
                       "params": {"mute": "true чтобы выключить"}},
    "os.brightness": {"func": brightness_set, "desc": "Установить яркость экрана 0-100",
                      "params": {"percent": "яркость"}},
    "os.empty_trash": {"func": empty_trash, "desc": "Очистить корзину"},
    "os.lock": {"func": lock_pc, "desc": "Заблокировать компьютер"},
    "os.shutdown": {"func": shutdown_pc, "desc": "Выключить ПК (с задержкой)",
                    "params": {"delay": "секунды", "restart": "true для перезагрузки"}},
    "os.cancel_power": {"func": cancel_power, "desc": "Отменить выключение/перезагрузку"},
    "game.boost_on": {"func": boost_on, "desc": "Игровой режим Overclock: приоритеты, питание, очистка ОЗУ"},
    "game.boost_off": {"func": boost_off, "desc": "Выключить игровой режим"},
    "system.clear_ram": {"func": clear_ram, "desc": "Очистить оперативную память"},
    "system.status": {"func": system_status, "desc": "Статус RAM и игрового режима"},
}
