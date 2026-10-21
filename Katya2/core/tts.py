import asyncio
import os
import tempfile
import threading
from pathlib import Path

from . import echo_guard

VOICE = "ru-RU-DmitryNeural"
VOICE_FEMALE = "ru-RU-SvetlanaNeural"
_TMP = Path(tempfile.gettempdir()) / "katya2_tts"
_TMP.mkdir(exist_ok=True)


def _synthesize(text, out_path, voice):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    asyncio.run(communicate.save(str(out_path)))


def _play(path):
    try:
        import sounddevice as sd
        import soundfile as sf
        data, sr = sf.read(str(path))
        sd.play(data, sr)
        sd.wait()
        return True
    except Exception:
        pass
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME)
        return True
    except Exception:
        return False


class Speaker:
    def __init__(self, voice=VOICE):
        self.voice = voice
        self._queue = []
        self._lock = threading.Lock()
        self._worker = None

    def say(self, text, voice=None):
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            self._queue.append((text, voice or self.voice))
            if not (self._worker and self._worker.is_alive()):
                self._worker = threading.Thread(target=self._loop, daemon=True)
                self._worker.start()

    def _loop(self):
        while True:
            with self._lock:
                if not self._queue:
                    return
                text, voice = self._queue.pop(0)
            try:
                out = _TMP / f"tts_{abs(hash(text)) % 10**8}.mp3"
                echo_guard.begin()
                _synthesize(text, out, voice)
                _play(out)
                out.unlink(missing_ok=True)
            except Exception:
                continue
            finally:
                echo_guard.end()


_default = None


def say(text, voice=None):
    global _default
    if _default is None:
        _default = Speaker()
    _default.say(text, voice)


def say_sync(text, voice=None):
    try:
        out = _TMP / f"tts_sync_{abs(hash(text)) % 10**8}.mp3"
        echo_guard.begin()
        _synthesize(text, out, voice or VOICE)
        _play(out)
        out.unlink(missing_ok=True)
    except Exception as e:
        return str(e)
    finally:
        echo_guard.end()
