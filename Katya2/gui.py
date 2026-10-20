import customtkinter as ctk

from core import brain, skills_loader, stt, tts

BG = "#0A0A0A"
PANEL = "#101418"
NEON = "#00E5FF"
NEON2 = "#39FF14"
DIM = "#5A6B75"
ERR = "#FF2E63"

ctk.set_appearance_mode("dark")


class KatyaApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Katya 2.0 — Hyper-Drive")
        self.geometry("900x680")
        self.configure(fg_color=BG)

        self.brain = brain.Brain()
        self.speaker = tts.Speaker()
        self.listener = None
        self.busy = False

        skills_loader.load_all()
        try:
            import skills.assistant_core as ac
            ac.init(notify=lambda t: self.after(0, self._notify, t))
        except Exception:
            pass

        self._build_ui()
        self._boot_message()

    def _build_ui(self):
        head = ctk.CTkFrame(self, fg_color=BG)
        head.pack(fill="x", padx=20, pady=(16, 6))
        ctk.CTkLabel(head, text="KATYA 2.0", font=("Consolas", 26, "bold"),
                     text_color=NEON).pack(side="left")
        ctk.CTkLabel(head, text="  HYPER-DRIVE", font=("Consolas", 13),
                     text_color=NEON2).pack(side="left")
        self.status = ctk.CTkLabel(head, text="● инициализация", font=("Consolas", 12),
                                   text_color=DIM)
        self.status.pack(side="right")

        self.log = ctk.CTkTextbox(self, fg_color=PANEL, text_color="#DCE7EC",
                                  font=("Consolas", 13), wrap="word",
                                  border_color="#1E2A33", border_width=1)
        self.log.pack(fill="both", expand=True, padx=20, pady=8)
        self.log.configure(state="disabled")

        bar = ctk.CTkFrame(self, fg_color=BG)
        bar.pack(fill="x", padx=20, pady=(4, 16))

        self.entry = ctk.CTkEntry(bar, placeholder_text="Скажи или напиши Кате...",
                                  fg_color=PANEL, border_color="#1E2A33",
                                  text_color="#DCE7EC", font=("Consolas", 13), height=44)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self._send())

        self.btn_send = ctk.CTkButton(bar, text="SEND", width=90, height=44,
                                      fg_color=NEON, text_color=BG,
                                      hover_color="#00B8CC", font=("Consolas", 13, "bold"),
                                      command=self._send)
        self.btn_send.pack(side="left", padx=(0, 8))

        self.btn_mic = ctk.CTkButton(bar, text="🎙  ГОВОРИ", width=130, height=44,
                                     fg_color="#132028", text_color=NEON,
                                     border_color=NEON, border_width=1,
                                     hover_color="#1B2E3A", font=("Consolas", 13),
                                     command=self._toggle_mic)
        self.btn_mic.pack(side="left")

        ctk.CTkLabel(self, text="skills: " + ", ".join(skills_loader.action_names()),
                     font=("Consolas", 10), text_color=DIM).pack(anchor="w", padx=22, pady=(0, 10))

    def _append(self, who, text, color):
        self.log.configure(state="normal")
        self.log.insert("end", f"{who}  ", color)
        self.log.insert("end", text + "\n\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _boot_message(self):
        ok = brain.available()
        self.status.configure(text="● онлайн" if ok else "● офлайн (нет ollama)",
                              text_color=NEON2 if ok else ERR)
        self._append("KATYA", "Воу, привет. Система прогрета, навыки подгружены. "
                              "Что взламываем сегодня?", NEON)
        if not ok:
            self._append("СИСТЕМА", "Ollama не найдена на 127.0.0.1:11434. "
                                    "Запусти `ollama serve` и модель qwen2.5:7b.", ERR)

    def _notify(self, text):
        self._append("KATYA", text, NEON2)
        self.speaker.say(text)

    def _send(self):
        text = self.entry.get().strip()
        if not text or self.busy:
            return
        self.entry.delete(0, "end")
        self._append("ВЫ", text, "#8FA6B2")
        self._handle(text)

    def _handle(self, text):
        self.busy = True
        self.status.configure(text="● думаю...", text_color=NEON)
        import threading

        def _worker():
            result = self.brain.ask(text)
            action = result.get("action")
            if action:
                name = action.get("name")
                args = action.get("args") or {}
                self.after(0, lambda: self._append("SKILL", f"{name} {args}", DIM))
                out = skills_loader.run(name, args)
                result = self.brain.ask(text, tool_result={"name": name, "result": out})
            self.after(0, self._show_reply, result)

        threading.Thread(target=_worker, daemon=True).start()

    def _show_reply(self, result):
        reply = result.get("reply", "...")
        self._append("KATYA", reply, NEON)
        self.status.configure(text="● онлайн", text_color=NEON2)
        self.speaker.say(reply)
        self.busy = False

    def _toggle_mic(self):
        if self.listener and self.listener.running:
            self.listener.stop()
            self.btn_mic.configure(text="🎙  ГОВОРИ", fg_color="#132028")
            self.status.configure(text="● онлайн", text_color=NEON2)
            return
        if self.listener is None:
            self.listener = stt.Listener(on_text=lambda t: self.after(0, self._on_voice, t))
        self.status.configure(text="● гружу модель...", text_color=NEON)
        self.update_idletasks()

        def _ready():
            self.listener.start()
            if self.listener.error:
                self.after(0, lambda: self._append("СИСТЕМА",
                                                   "Микрофон/Vosk: " + self.listener.error, ERR))
                self.after(0, lambda: self.status.configure(text="● онлайн", text_color=NEON2))
                return
            self.after(0, lambda: self.btn_mic.configure(text="⏹  СЛУШАЮ", fg_color="#2A0B16"))
            self.after(0, lambda: self.status.configure(text="● слушаю", text_color=NEON))

        import threading
        threading.Thread(target=_ready, daemon=True).start()

    def _on_voice(self, text):
        self._append("ВЫ (голос)", text, "#8FA6B2")
        self._handle(text)


def run():
    app = KatyaApp()
    app.mainloop()
