# Katya 2.10.1 — Anti-Alice Swarm Edition 🛰️

**Полностью автономный локальный ИИ-агент для Windows на базе Ollama.** Киберпанк HUD, голосовое управление, Runtime Self-Evolution (самокодинг), Computer Use, всеядный гейминг-аналитик **Cyber-Coach** и открытая архитектура плагинов.

## ⚡ Установка в один клик (v2.10.1)

**Для запуска версии 2.10.1 просто скачайте и запустите `Katya_2.10.1_Setup.exe`.** Программа сама установит локальный ИИ, скачает модели для анализа игр и запустит неоновый интерфейс. **Аккаунты не нужны!**

Установщик делает всё сам, с красивой шкалой прогресса:
1. проверяет Python и библиотеки, тихо доустанавливает недостающие;
2. находит Ollama, а если её нет — сам тихо скачивает и ставит `OllamaSetup.exe /silent`;
3. качает модель `gemma3:4b` (текст + зрение, работает на GPU) с прогресс-баром;
4. молча закрывается и мгновенно открывает неоновый интерфейс Кати.

![Katya 2.10.1](banner.svg)

![Python](https://img.shields.io/badge/python-3.11%2B-00E5FF?style=flat-square)
![Ollama](https://img.shields.io/badge/Ollama-gemma3%3A4b%20(GPU)-39FF14?style=flat-square)
![UI](https://img.shields.io/badge/UI-CustomTkinter-00E5FF?style=flat-square)
![STT](https://img.shields.io/badge/STT-Vosk-39FF14?style=flat-square)
![TTS](https://img.shields.io/badge/TTS-edge--tts%20Dmitry-00E5FF?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-39FF14?style=flat-square)

---

## ✨ Что это

Катя 2.10 — свободный локальный агент с характером девушки-программиста. Работает целиком на твоём ПК: **без облаков, без аккаунтов, без цензуры облачных ассистентов**. Она рулит Windows, разгоняет систему под игры, работает с экраном и мышью, анализирует геймплей глазами vision-модели и **сама пишет себе новые навыки** прямо во время работы.

## 🧬 Фича №1 — Runtime Self-Evolution (Самокодинг)

Если у Кати нет готового плагина под задачу — она не сдаётся, а **пишет новый Python-код на ходу** локальной моделью:

1. `core/self_coder.py` просит Ollama написать изолированный Python-файл (без markdown).
2. Код валидируется: синтаксис, наличие `ACTIONS`, блоклист опасных конструкций.
3. `core/skills_loader.py::save_and_run_learned_skill()` сохраняет плагин в `skills/` и подхватывает через `importlib`.
4. **Self-Healing**: если плагин упал, Катя читает `traceback` и просит модель исправить — до N попыток.

> Пример: «Катя, сделай навык, который показывает заряд батареи» → появляется рабочий `skills/auto_*.py`.

## 🎮 Фича №2 — Протокол Cyber-Coach (гейминг-аналитик)

Всеядный тренер по любой игре — **Roblox, шутеры, RPG**:

- `skills/game_analyst.py` захватывает кадр активной игры через **`mss`** (сверхбыстро, без просадки FPS).
- Кадр сжимается и уходит в локальную **vision-модель `gemma3:4b`** через API Ollama — целиком на GPU.
- Промпт «киберспортивный тренер» разбирает интерфейс, HP/ману, кулдауны скиллов, позицию.
- Вердикт мгновенно озвучивается через `core/tts.py`.

**Голосовые триггеры:** «Катя, оцени мою игру», «как я играю?», «вруби тренера» → запускается непрерывный цикл (1 кадр / 3.5 сек), Катя подтверждает: *«Протокол Cyber-Coach запущен. Показывай свой билд, босс, я слежу за каткой»*. Остановка — «выключи тренера».

Особый режим для **Roblox**: если игрок за класс Тень со способностями Warrior — тренер учитывает это в разборе комбо.

## 🖱️ Фича №3 — Computer Use

`skills/computer_use.py` через `pyautogui`: клики по координатам, ввод текста, горячие клавиши и **цепочки действий** («click 640 360; type привет; hotkey ctrl+s»).

## 👁️ Фича №4 — Vision OCR

`skills/vision_ocr.py`: скриншот экрана/области, OCR через `pytesseract` (rus+eng), а при его отсутствии — распознавание vision-моделью `gemma3:4b`. Умеет разбирать **ошибки в коде с экрана**.

## 🕶️ Фича №5 — Протоколы Marvel

`skills/marvel_protocols.py`:
- **«Максимальный Overclock»** — высокая производительность Windows, очистка ОЗУ, понижение приоритета фонового софта (буст FPS).
- **«Спрячь палево»** — мгновенно свернуть все окна, замьютить звук и заблокировать экран (Win+L).

## 🔇 Echo Guard

`core/echo_guard.py` — пока Катя говорит, `core/stt.py` игнорирует микрофон, чтобы она не триггерилась на собственный голос из динамиков.

## 🧩 Открытость для сторонних плагинов

Архитектура полностью открыта: **любой файл** в `skills/` со словарём `ACTIONS` автоматически подхватывается на старте. Пиши свой плагин, кидай в папку — Катя его увидит. Идеально для разработчиков, которые любят форкать и дописывать.

```python
# skills/my_plugin.py
def hello(name="мир"):
    return f"Привет, {name}!"

ACTIONS = {
    "my.hello": {"func": hello, "desc": "Поздороваться", "params": {"name": "имя"}},
}
```

## 🛠️ Стек

- **Интерфейс:** CustomTkinter (HUD, палитра `#0B0E12` + неон `#22D3EE` / `#34D399`)
- **Слух:** Vosk (автоскачивание `vosk-model-small-ru-0.22`)
- **Голос:** edge-tts (`ru-RU-DmitryNeural`)
- **Мозг:** Ollama `http://localhost:11434` — `gemma3:4b` (текст + vision, 100% GPU)
- **Компьютер:** pyautogui · mss · Pillow · opencv-python · pytesseract
- **Система:** psutil · pycaw · screen_brightness_control · pywinauto · yt-dlp

## 🚀 Быстрый старт

```bat
:: 1) Установи Ollama: https://ollama.com/download
:: 2) Запусти:
ЗАПУСТИТЬ.bat
```

`ЗАПУСТИТЬ.bat` сам проверит Ollama, создаст venv, поставит зависимости, подтянет модель **`gemma3:4b`** (текст + vision, работает на GPU) и запустит Катю. Без регистраций и аккаунтов.

Вручную:

```bash
git clone https://github.com/kirill181024-cyber/katya.git
cd katya/Katya2
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull gemma3:4b
.venv\Scripts\pythonw.exe main.py
```

## 🗣️ Примеры команд

- «Катя, вруби тренера» — **Cyber-Coach** следит за каткой
- «Катя, оцени мою игру» / «как я играю?»
- «Катя, активируй Overclock» / «спрячь палево»
- «Катя, убавь громкость до 20» / «сделай яркость 70»
- «Катя, кликни 500 300» / «напиши привет в чат» / «нажми ctrl+c»
- «Катя, прочитай текст с экрана» / «найди ошибку на экране»
- «Катя, склей браузер и код» / «закрой телеграм жёстко»
- «Катя, скачай это» (ссылка в буфере)
- «Катя, сделай навык, который показывает заряд батареи» — **самообучение**

## 🧩 Архитектура

```
Katya2/
├─ main.py                  # точка входа
├─ gui.py                   # CustomTkinter HUD
├─ config.py                # Ollama URL, модель gemma3:4b, GPU-параметры
├─ ЗАПУСТИТЬ.bat            # one-click запуск
├─ core/
│  ├─ brain.py              # Ollama + агентный JSON-цикл + голосовые триггеры
│  ├─ skills_loader.py      # динамическая загрузка + save_and_run_learned_skill
│  ├─ self_coder.py         # Self-Coding Engine (генерация/валидация/retry)
│  ├─ echo_guard.py         # отсечка микрофона во время речи
│  ├─ stt.py                # Vosk + автозагрузка модели
│  └─ tts.py                # edge-tts Dmitry
└─ skills/                  # изолированные плагины (ACTIONS dict)
   ├─ os_control.py         # процессы, громкость, яркость, питание, Overclock
   ├─ window_manager.py     # раскладка/фокус/скрытие окон
   ├─ computer_use.py       # мышь, клавиатура, цепочки действий (pyautogui)
   ├─ vision_ocr.py         # скриншот + OCR + анализ ошибок
   ├─ game_analyst.py       # Cyber-Coach: mss + gemma3:4b (GPU) + TTS
   ├─ marvel_protocols.py   # Overclock + «Спрячь палево»
   ├─ media.py              # буфер + yt-dlp (видео/аудио/пачка ссылок)
   ├─ media_downloader.py   # yt-dlp скачивание
   ├─ assistant_core.py     # таймеры, календарь, заметки
   └─ self_coding.py        # навык-обёртка самообучения
```

## 📄 License

MIT
