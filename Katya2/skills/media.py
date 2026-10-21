"""Медиа-комбайн: перехват ссылок из буфера и скачивание через yt-dlp.

Дополняет media_downloader: удобные голосовые команды
«скачай это», «скачай только звук», «что качается».
"""

from yt_dlp import YoutubeDL

from skills import media_downloader as md


def download_clipboard_video():
    return md.download_clipboard(audio_only=False)


def download_clipboard_audio():
    return md.download_clipboard(audio_only=True)


def download_link(url, audio_only=False):
    return md.download(url, audio_only=audio_only)


def progress():
    return md.progress()


def _bulk(urls, audio_only=False):
    if isinstance(urls, str):
        urls = [u.strip() for u in urls.replace(",", "\n").split() if u.strip()]
    if not urls:
        return "Нет ссылок для загрузки."
    res = [md.download(u, audio_only=audio_only) for u in urls]
    return f"Запущено {len(urls)} загрузок. " + " ".join(res)


ACTIONS = {
    "media.clip_video": {"func": download_clipboard_video,
                         "desc": "Скачать видео по ссылке из буфера обмена"},
    "media.clip_audio": {"func": download_clipboard_audio,
                         "desc": "Скачать только звук по ссылке из буфера обмена"},
    "media.link": {"func": download_link, "desc": "Скачать видео/аудио по ссылке",
                   "params": {"url": "ссылка", "audio_only": "true только звук"}},
    "media.bulk": {"func": _bulk, "desc": "Скачать несколько ссылок сразу",
                   "params": {"urls": "ссылки через пробел/запятую",
                              "audio_only": "true только звук"}},
    "media.queue": {"func": progress, "desc": "Показать очередь и прогресс загрузок"},
}
