import json
import queue
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_PATH = MODELS_DIR / MODEL_NAME


def model_ready():
    return MODEL_PATH.exists() and (MODEL_PATH / "am").exists()


def ensure_model(progress_cb=None):
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    if model_ready():
        return MODEL_PATH
    zip_path = MODELS_DIR / f"{MODEL_NAME}.zip"

    def _hook(blocks, bs, total):
        if progress_cb and total > 0:
            progress_cb(min(100, int(blocks * bs / total * 100)))

    urllib.request.urlretrieve(MODEL_URL, zip_path, reporthook=_hook)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(MODELS_DIR)
    zip_path.unlink(missing_ok=True)
    return MODEL_PATH


class Listener:
    def __init__(self, on_text, sample_rate=16000):
        self.on_text = on_text
        self.sample_rate = sample_rate
        self._stop = threading.Event()
        self._thread = None
        self._loaded = False
        self.error = None

    def _load(self):
        try:
            import vosk
            import sounddevice as sd
            vosk.SetLogLevel(-1)
            ensure_model()
            self._rec = vosk.KaldiRecognizer(
                vosk.Model(str(MODEL_PATH)), self.sample_rate)
            self._sd = sd
            self._loaded = True
        except Exception as e:
            self.error = str(e)

    def _run(self):
        try:
            import vosk
            q = queue.Queue()

            def callback(indata, frames, time_info, status):
                q.put(bytes(indata))

            with self._sd.RawInputStream(
                samplerate=self.sample_rate, blocksize=8000, dtype="int16",
                channels=1, callback=callback,
            ):
                while not self._stop.is_set():
                    try:
                        data = q.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if self._rec.AcceptWaveform(data):
                        text = json.loads(self._rec.Result()).get("text", "").strip()
                        if text:
                            self.on_text(text)
        except Exception as e:
            self.error = str(e)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self._loaded:
            self._load()
        if not self._loaded:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())
