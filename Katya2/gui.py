import math
import threading
from pathlib import Path

import customtkinter as ctk

from core import brain, skills_loader, stt, tts

# ---- Modern dark palette -------------------------------------------------
BG = "#0B0E12"
SURFACE = "#11161C"
SURFACE_2 = "#161D25"
STROKE = "#1E2833"
TEXT = "#E6EEF4"
TEXT_DIM = "#7C8D9C"
ACCENT = "#22D3EE"
ACCENT_2 = "#34D399"
ACCENT_DEEP = "#0891B2"
USER_BUBBLE = "#1B2A38"
ERR = "#F43F5E"
WARN = "#FBBF24"

FONT = "Segoe UI"
MONO = "Consolas"

VERSION = "2.10.1"

ctk.set_appearance_mode("dark")


class Bubble(ctk.CTkFrame):
    """Chat message rendered as a rounded card."""

    def __init__(self, master, who, text, kind="katya"):
        super().__init__(master, fg_color="transparent")

        meta = {
            "user": ("Вы", ACCENT, SURFACE_2, "e"),
            "katya": ("Катя", ACCENT_2, SURFACE, "w"),
            "skill": ("Навык", TEXT_DIM, SURFACE, "w"),
            "system": ("Система", ERR, SURFACE, "w"),
        }
        label, color, bg, anchor = meta.get(kind, meta["katya"])

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=2, anchor=anchor)

        ctk.CTkLabel(row, text=label, font=(MONO, 11, "bold"),
                     text_color=color).pack(anchor=anchor, padx=6)

        card = ctk.CTkFrame(row, fg_color=bg, corner_radius=14,
                            border_width=1, border_color=STROKE)
        card.pack(anchor=anchor, padx=6, pady=(1, 0))

        ctk.CTkLabel(card, text=text, font=(FONT, 13), text_color=TEXT,
                     justify="left", anchor="w", wraplength=560).pack(padx=14, pady=10)


class KatyaApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Katya {VERSION} — Hyper-Drive")
        self.geometry("1040x720")
        self.minsize(880, 600)
        self.configure(fg_color=BG)

        ico = Path(__file__).resolve().parent / "katya.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

        self.brain = brain.Brain()
        self.speaker = tts.Speaker()
        self.listener = None
        self.busy = False
        self._pulse = 0
        self._pulse_job = None

        skills_loader.load_all()
        try:
            import skills.assistant_core as ac
            ac.init(notify=lambda t: self.after(0, self._notify, t))
        except Exception:
            pass
        try:
            import skills.game_analyst as ga
            ga.init(notify=lambda t: self.after(0, self._append, "ТРЕНЕР", t, "skill"))
        except Exception:
            pass

        self._build_sidebar()
        self._build_chat()
        self._boot_message()

    # ------------------------------------------------------------------ UI
    def _build_sidebar(self):
        side = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, width=260)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(22, 6))
        ctk.CTkLabel(brand, text="KATYA", font=(FONT, 26, "bold"),
                     text_color=TEXT).pack(side="left")
        ctk.CTkLabel(brand, text=f" {VERSION}", font=(FONT, 26, "bold"),
                     text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(side, text="HYPER-DRIVE", font=(MONO, 11),
                     text_color=TEXT_DIM).pack(anchor="w", padx=22)

        ctk.CTkFrame(side, fg_color=STROKE, height=1).pack(fill="x", padx=20, pady=16)

        card = ctk.CTkFrame(side, fg_color=SURFACE_2, corner_radius=12)
        card.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkLabel(card, text="СТАТУС", font=(MONO, 10), text_color=TEXT_DIM).pack(
            anchor="w", padx=14, pady=(10, 0))
        self.status = ctk.CTkLabel(card, text="инициализация", font=(FONT, 14, "bold"),
                                   text_color=WARN)
        self.status.pack(anchor="w", padx=14)
        self.status_dot = ctk.CTkLabel(card, text="○  ожидание", font=(MONO, 11),
                                       text_color=TEXT_DIM)
        self.status_dot.pack(anchor="w", padx=14, pady=(0, 10))

        ctk.CTkLabel(side, text="НАВЫКИ", font=(MONO, 10),
                     text_color=TEXT_DIM).pack(anchor="w", padx=22, pady=(4, 6))

        skills_box = ctk.CTkScrollableFrame(side, fg_color="transparent")
        skills_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for name in skills_loader.action_names():
            chip = ctk.CTkFrame(skills_box, fg_color=SURFACE_2, corner_radius=8)
            chip.pack(fill="x", pady=3)
            ctk.CTkLabel(chip, text="● ", font=(MONO, 12), text_color=ACCENT_2).pack(
                side="left", padx=(10, 0), pady=6)
            ctk.CTkLabel(chip, text=name, font=(MONO, 11), text_color=TEXT).pack(
                side="left", padx=(0, 10), pady=6)

        ctk.CTkLabel(side, text="local LLM · self-coding", font=(MONO, 10),
                     text_color=TEXT_DIM).pack(anchor="w", padx=22, pady=(0, 16))

    def _build_chat(self):
        right = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        right.pack(side="left", fill="both", expand=True)

        top = ctk.CTkFrame(right, fg_color=BG)
        top.pack(fill="x", padx=24, pady=(20, 8))
        ctk.CTkLabel(top, text="Диалог", font=(FONT, 18, "bold"),
                     text_color=TEXT).pack(side="left")
        ctk.CTkButton(top, text="Очистить", width=90, height=30,
                      fg_color=SURFACE_2, text_color=TEXT_DIM, hover_color=STROKE,
                      font=(FONT, 12), corner_radius=8, command=self._clear).pack(side="right")

        self.feed = ctk.CTkScrollableFrame(right, fg_color=SURFACE,
                                           corner_radius=16, border_width=1,
                                           border_color=STROKE)
        self.feed.pack(fill="both", expand=True, padx=24, pady=6)

        bar = ctk.CTkFrame(right, fg_color=SURFACE, corner_radius=16,
                           border_width=1, border_color=STROKE)
        bar.pack(fill="x", padx=24, pady=(10, 20))

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=12)

        self.mic_btn = ctk.CTkButton(inner, text="🎙", width=52, height=46,
                                     fg_color=SURFACE_2, text_color=ACCENT,
                                     hover_color=USER_BUBBLE, corner_radius=12,
                                     border_width=1, border_color=STROKE,
                                     font=(FONT, 20), command=self._toggle_mic)
        self.mic_btn.pack(side="left", padx=(0, 10))

        self.entry = ctk.CTkEntry(inner, placeholder_text="Спроси или прикажи Кате...",
                                  fg_color=BG, border_color=STROKE, border_width=1,
                                  text_color=TEXT, font=(FONT, 13), height=46,
                                  corner_radius=12)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.entry.bind("<Return>", lambda e: self._send())

        self.btn_send = ctk.CTkButton(inner, text="Отправить", width=120, height=46,
                                      fg_color=ACCENT, text_color="#04222A",
                                      hover_color=ACCENT_DEEP, corner_radius=12,
                                      font=(FONT, 13, "bold"), command=self._send)
        self.btn_send.pack(side="left")

    # --------------------------------------------------------------- helpers
    def _append(self, who, text, kind="katya"):
        Bubble(self.feed, who, text, kind).pack(fill="x", pady=2)
        self.after(30, lambda: self.feed._parent_canvas.yview_moveto(1.0))

    def _clear(self):
        for w in self.feed.winfo_children():
            w.destroy()

    def _set_status(self, text, sub, color):
        self.status.configure(text=text, text_color=color)
        self.status_dot.configure(text=sub, text_color=color)

    def _boot_message(self):
        ok = brain.available()
        self._set_status("Онлайн" if ok else "Оффлайн",
                         "● ollama подключена" if ok else "● ollama недоступна",
                         ACCENT_2 if ok else ERR)
        self._append("KATYA", "Воу, привет. Система прогрета, навыки подгружены. "
                              "Что взламываем сегодня?", "katya")
        if not ok:
            self._append("СИСТЕМА", "Ollama не найдена на 127.0.0.1:11434. "
                                    "Запусти `ollama serve` и модель gemma3:4b.", "system")

    def _notify(self, text):
        self._append("KATYA", text, "katya")
        self.speaker.say(text)

    def _send(self):
        text = self.entry.get().strip()
        if not text or self.busy:
            return
        self.entry.delete(0, "end")
        self._append("ВЫ", text, "user")
        self._handle(text)

    def _handle(self, text):
        self.busy = True
        self._set_status("Думаю", "◌ обработка запроса", ACCENT)

        trigger = brain.detect_trigger(text)
        if trigger:
            self._append("НАВЫК", trigger, "skill")
            out = skills_loader.run(trigger, {})
            self._append("KATYA", out, "katya")
            self.speaker.say(out)
            self.busy = False
            self._set_status("Онлайн", "● ollama подключена", ACCENT_2)
            return

        def _worker():
            result = self.brain.ask(text)
            action = result.get("action")
            if action:
                name = action.get("name")
                args = action.get("args") or {}
                self.after(0, lambda: self._append("НАВЫК", f"{name}  {args or ''}", "skill"))
                out = skills_loader.run(name, args)
                result = self.brain.ask(text, tool_result={"name": name, "result": out})
            self.after(0, self._show_reply, result)

        threading.Thread(target=_worker, daemon=True).start()

    def _show_reply(self, result):
        reply = result.get("reply", "...")
        self._append("KATYA", reply, "katya")
        self._set_status("Онлайн", "● ollama подключена", ACCENT_2)
        self.speaker.say(reply)
        self.busy = False

    # ------------------------------------------------------------------- mic
    def _toggle_mic(self):
        if self.listener and self.listener.running:
            self.listener.stop()
            self._stop_pulse()
            self.mic_btn.configure(text="🎙", fg_color=SURFACE_2, border_color=STROKE,
                                   text_color=ACCENT)
            self._set_status("Онлайн", "● ollama подключена", ACCENT_2)
            return
        if self.listener is None:
            self.listener = stt.Listener(on_text=lambda t: self.after(0, self._on_voice, t))
        self._set_status("Загрузка", "◌ модель распознавания...", WARN)

        def _ready():
            self.listener.start()
            if self.listener.error:
                err = self.listener.error
                self.after(0, lambda: self._append("СИСТЕМА", "Микрофон/Vosk: " + err, "system"))
                self.after(0, lambda: self._set_status("Онлайн", "● ollama подключена", ACCENT_2))
                return
            self.after(0, self._start_pulse)
            self.after(0, lambda: self._set_status("Слушаю", "● идёт запись", ACCENT_2))

        threading.Thread(target=_ready, daemon=True).start()

    def _start_pulse(self):
        self.mic_btn.configure(fg_color=ACCENT, text_color="#04222A", text="■",
                               border_color=ACCENT)
        self._pulse_job = self.after(120, self._pulse_tick)

    def _pulse_tick(self):
        self._pulse += 1
        alpha = 0.55 + 0.45 * math.sin(self._pulse * 0.9)
        r = int(8 + 60 * alpha)
        g = int(120 + 100 * alpha)
        b = int(150 + 60 * alpha)
        self.mic_btn.configure(text_color="#04222A",
                               fg_color=f"#{r:02x}{g:02x}{b:02x}")
        self._pulse_job = self.after(120, self._pulse_tick)

    def _stop_pulse(self):
        if self._pulse_job:
            self.after_cancel(self._pulse_job)
            self._pulse_job = None

    def _on_voice(self, text):
        self._append("ВЫ (голос)", text, "user")
        self._handle(text)


def run():
    app = KatyaApp()
    app.mainloop()
