"""Echo Guard — отсечка микрофона.

Пока Катя говорит, модуль STT должен игнорировать входящий звук,
чтобы не срабатывать на собственный голос из динамиков.
"""

import threading
import time

_lock = threading.Lock()
_speaking = 0
_until = 0.0
_extra = 0.0


def begin(hold=0.0):
    """Отметить начало озвучки. hold — гарантированная пауза в секундах."""
    global _speaking, _until
    with _lock:
        _speaking += 1
        _until = max(_until, time.time() + hold)


def end(tail=0.6):
    """Озвучка закончена. tail — пауза после, чтобы добить эхо."""
    global _speaking, _until
    with _lock:
        if _speaking > 0:
            _speaking -= 1
        _until = max(_until, time.time() + tail)


def set_extra(seconds):
    """Дополнительная (внешняя) блокировка, напр. tts отдельно."""
    global _extra
    with _lock:
        _extra = max(_extra, time.time() + seconds)


def muted():
    """True, если сейчас микрофон должен быть заглушён."""
    with _lock:
        if _speaking > 0:
            return True
        now = time.time()
        return now < _until or now < _extra


def busy():
    return muted()
