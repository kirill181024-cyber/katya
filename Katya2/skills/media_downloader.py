import os
import re
import threading
from pathlib import Path

from yt_dlp import YoutubeDL

DOWNLOADS = Path(os.path.expanduser("~")) / "Downloads"
_TASKS = {}
_LOCK = threading.Lock()
_counter = 0


def _clipboard():
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        text = r.clipboard_get()
        r.destroy()
        return (text or "").strip()
    except Exception:
        return ""


def _platform(url):
    url = (url or "").lower()
    for key, name in (("youtube.com", "YouTube"), ("youtu.be", "YouTube"),
                      ("tiktok.com", "TikTok"), ("vk.com", "VK"), ("vkvideo", "VK"),
                      ("rutube.ru", "Rutube"), ("instagram.com", "Instagram"),
                      ("twitter.com", "X"), ("x.com", "X")):
        if key in url:
            return name
    return "сайт"


def _hook(tid):
    def hook(d):
        with _LOCK:
            t = _TASKS.get(tid)
            if not t:
                return
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                got = d.get("downloaded_bytes") or 0
                t["percent"] = round(got / total * 100, 1) if total else 0
                t["speed"] = d.get("speed")
            elif d.get("status") == "finished":
                t["percent"] = 100
    return hook


def download(url, audio_only=False):
    global _counter
    url = (url or "").strip()
    if not url.startswith("http"):
        return "Ссылка не найдена. Скопируй ссылку и повтори."
    with _LOCK:
        _counter += 1
        tid = str(_counter)
        _TASKS[tid] = {"url": url, "percent": 0, "status": "started"}

    def _worker():
        opts = {
            "outtmpl": str(DOWNLOADS / "%(title).120s.%(ext)s"),
            "progress_hooks": [_hook(tid)],
            "noplaylist": True, "quiet": True, "no_warnings": True,
        }
        if str(audio_only).lower() in ("1", "true", "да"):
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
        else:
            opts["format"] = "bestvideo+bestaudio/best"
            opts["merge_output_format"] = "mp4"
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            with _LOCK:
                _TASKS[tid].update(status="done", percent=100, title=info.get("title", "файл"))
        except Exception as e:
            with _LOCK:
                _TASKS[tid].update(status="error", error=str(e)[:200])

    threading.Thread(target=_worker, daemon=True).start()
    return f"Качаю с {_platform(url)} в Загрузки. Следи за прогрессом."


def download_clipboard(audio_only=False):
    url = _clipboard()
    if not url.startswith("http"):
        return "В буфере нет ссылки. Скопируй и повтори."
    return download(url, audio_only=audio_only)


def progress(task_id=None):
    with _LOCK:
        if not _TASKS:
            return "Активных загрузок нет."
        if task_id:
            t = _TASKS.get(str(task_id))
            return f"{task_id}: {t}" if t else f"Задача {task_id} не найдена."
        lines = []
        for tid, t in _TASKS.items():
            if t["status"] == "done":
                lines.append(f"{t.get('title', tid)} — готово")
            elif t["status"] == "error":
                lines.append(f"{tid} — ошибка: {t.get('error')}")
            else:
                sp = t.get("speed")
                lines.append(f"{tid} — {t.get('percent', 0)}%" + (f" ({sp/1024/1024:.1f} МБ/с)" if sp else ""))
    return "Загрузки:\n" + "\n".join(lines)


ACTIONS = {
    "media.download": {"func": download, "desc": "Скачать видео/аудио по ссылке в Загрузки",
                       "params": {"url": "ссылка", "audio_only": "true только звук"}},
    "media.download_clipboard": {"func": download_clipboard, "desc": "Скачать ссылку из буфера обмена (скачай это)",
                                 "params": {"audio_only": "true только звук"}},
    "media.progress": {"func": progress, "desc": "Прогресс текущих загрузок",
                       "params": {"task_id": "опционально id задачи"}},
}
