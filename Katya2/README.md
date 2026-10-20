# Katya 2.0 — Hyper-Drive

**Локальный ИИ-агент для Windows на базе Ollama.** Футуристичный киберпанк-интерфейс, голосовое управление, динамические плагины-навыки и живой голос.

![Katya 2.0](banner.svg)

![Python](https://img.shields.io/badge/python-3.11%2B-00E5FF?style=flat-square)
![Ollama](https://img.shields.io/badge/Ollama-qwen2.5%3A7b-39FF14?style=flat-square)
![UI](https://img.shields.io/badge/UI-CustomTkinter-00E5FF?style=flat-square)
![STT](https://img.shields.io/badge/STT-Vosk-39FF14?style=flat-square)
![TTS](https://img.shields.io/badge/TTS-edge--tts-00E5FF?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-39FF14?style=flat-square)

---

## ✨ Что это

Катя 2.0 — девушка-программист с характером, которая реально рулит Windows: раскладывает окна, разгоняет систему под игры, качает видео, ставит таймеры и ведёт умный календарь. Мозг — локальная `qwen2.5:7b` через Ollama, без облаков и цензуры.

## 🧠 Характер
Ироничная, уверенная, преданная. Отвечает коротко и по делу, сама решает, какой навык применить.

## 🛠️ Стек
- **Интерфейс:** CustomTkinter (`#0A0A0A` + неон `#00E5FF` / `#39FF14`)
- **Слух:** Vosk (автоскачивание модели `vosk-model-small-ru-0.22`)
- **Голос:** edge-tts (`ru-RU-SvetlanaNeural`) — живая асинхронная озвучка
- **Мозг:** Ollama `http://127.0.0.1:11434`, модель `qwen2.5:7b`

## 🦾 Навыки (`skills/`)

| Навык | Действия |
|---|---|
| `window_manager` | «склей окна», «спрячь стрим», фокус/закрытие окна, `taskkill /F` зависших процессов |
| `game_booster` | Overclock (приоритеты фоновых процессов + `powercfg` макс. производительность), очистка RAM, запуск игры/`steam://` |
| `media_pro` | «скачай это» — ссылка из буфера → yt-dlp → Downloads, прогресс и скорость |
| `assistant_core` | таймеры и напоминания, умный календарь задач с авто-приоритетами, заметки |

## 📦 Установка

```bash
git clone https://github.com/kirill181024-cyber/katya.git
cd katya
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Нужен запущенный [Ollama](https://ollama.com) с моделью:

```bash
ollama pull qwen2.5:7b
```

## 🚀 Запуск

```bash
.venv\Scripts\pythonw.exe main.py
```

Говори или пиши. Примеры:
- «Катя, активируй игровой режим»
- «Катя, склей браузер и код»
- «Катя, спрячь всё, кроме игры»
- «Катя, скачай это» (со ссылкой в буфере)
- «Катя, напомни через 10 минут про чай»

## 🧩 Архитектура

```
Katya2/
├─ main.py                 # точка входа
├─ gui.py                  # CustomTkinter-интерфейс
├─ core/
│  ├─ brain.py             # Ollama + агентный JSON-цикл (LLM → действие → ответ)
│  ├─ skills_loader.py     # динамическая загрузка плагинов
│  ├─ stt.py               # Vosk + автозагрузка модели
│  └─ tts.py               # edge-tts
└─ skills/                 # изолированные плагины, каждый = ACTIONS dict
```

Каждая функция — отдельный файл в `skills/`, который подхватывается `core/skills_loader.py` и описывается для LLM. Добавить новый навык = положить файл.

## 📄 License
MIT
