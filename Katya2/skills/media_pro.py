import os
import re
import threading
from pathlib import Path

from yt_dlp import YoutubeDL

DOWNLOADS = Path(os.path.expanduser("~")) / "Downloads"
_TASKS = {}
_LOCK = threading.Lock()


def _clipboard():
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        text = r.clipboard_get()
        r.destroy()
        return text.strip()
    except Exception:
        return ""


def detect_platform(url):
    url = (url or "").lower()
    if "youtube.com" in url or "youtu.be" in url:
        return "YouTube"
    if "tiktok.com" in url:
        return "TikTok"
    if "vk.com" in url or "vkvideo" in url:
        return "VK"
    if "rutube.ru" in url:
        return "Rutube"
    if "instagram.com" in url:
        return "Instagram"
    if "twitter.com" in url or "x.com" in url:
        return "X"
    return "сайт"


def _progress_hook(task_id):
    def hook(d):
        with _LOCK:
            if task_id not in _TASKS:
                return
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                got = d.get("downloaded_bytes") or 0
                _TASKS[task_id]["percent"] = round(got / total * 100, 1) if total else 0
                _TASKS[task_id]["speed"] = d.get("speed")
            elif d.get("status") == "finished":
                _TASKS[task_id]["percent"] = 100
    return hook


def download_url(url, audio_only=False):
    url = (url or "").strip()
    if not url.startswith("http"):
        return "Ссылка не найдена в буфере."
    task_id = str(len(_TASKS) + 1) + "-" + re.sub(r"\W+", "", url)[-12:]
    with _LOCK:
        _TASKS[task_id] = {"url": url, "percent": 0, "status": "started"}

    def _worker():
        opts = {
            "outtmpl": str(DOWNLOADS / "%(title).120s.%(ext)s"),
            "progress_hooks": [_progress_hook(task_id)],
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
        if audio_only:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
        else:
            opts["format"] = "bestvideo+bestaudio/best"
            opts["merge_output_format"] = "mp4"
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            title = info.get("title", "файл")
            with _LOCK:
                _TASKS[task_id].update(status="done", percent=100, title=title)
        except Exception as e:
            with _LOCK:
                _TASKS[task_id].update(status="error", error=str(e)[:200])

    threading.Thread(target=_worker, daemon=True).start()
    plat = detect_platform(url)
    return f"Качаю с {plat} в Загрузки. Следи за прогрессом."


def download_clipboard(audio_only=False):
    url = _clipboard()
    if not url.startswith("http"):
        return "В буфере обмена нет ссылки. Скопируй и повтори."
    return download_url(url, audio_only=audio_only)


def progress(task_id=None):
    with _LOCK:
        if not _TASKS:
            return "Активных загрузок нет."
        if task_id:
            t = _TASKS.get(task_id)
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
    "media.download": {
        "func": download_url,
        "desc": "Скачать видео/аудио по ссылке в папку Загрузки",
        "params": {"url": "ссылка", "audio_only": "true если только звук (mp3)"},
    },
    "media.download_clipboard": {
        "func": download_clipboard,
        "desc": "Скачать то, что в буфере обмена (скачай это)",
        "params": {"audio_only": "true если только звук"},
    },
    "media.progress": {
        "func": progress,
        "desc": "Показать прогресс текущих загрузок",
        "params": {"task_id": "опционально id задачи"},
    },
}
