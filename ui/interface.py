"""
Katya 2.11.0 — «Пятница» HUD.

A deep-black, neon-cyan command deck built with CustomTkinter. The Tk thread
only paints widgets; voice, LLM inference and protocol actions live in a
dedicated asyncio daemon and worker threads.
"""

from __future__ import annotations

import asyncio
import logging
import math
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from typing import Any

import customtkinter as ctk

import config
from core.engine import KatyaEngine

logger = logging.getLogger(__name__)

COLORS = {
    "bg": "#03060A",
    "panel": "#071018",
    "panel2": "#0A1620",
    "panel3": "#0D1E29",
    "neon": "#00F0FF",
    "neon_soft": "#0BB8C8",
    "neon_dim": "#0A4E58",
    "text": "#D9F8FF",
    "muted": "#6F9099",
    "ok": "#31FFB4",
    "warn": "#FFB020",
    "error": "#FF3B6B",
    "line": "#123440",
}

PROVIDER_LABELS = {key: value["label"] for key, value in config.PROVIDERS.items()}
LABEL_TO_PROVIDER = {label: key for key, label in PROVIDER_LABELS.items()}


class AsyncRuntime:
    """One asyncio loop in a daemon thread, safe to submit from Tk."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="KatyaAsyncRuntime",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise RuntimeError("Не удалось запустить asyncio runtime")

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        loop.set_exception_handler(self._exception_handler)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            finally:
                loop.close()

    @staticmethod
    def _exception_handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        logger.error("Async loop error: %s", context.get("message"))
        exception = context.get("exception")
        if exception:
            logger.error("Async exception", exc_info=exception)

    def submit(self, coroutine):  # noqa: ANN001, ANN201
        loop = self.loop
        if loop is None or loop.is_closed():
            coroutine.close()
            raise RuntimeError("Async runtime остановлен")
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        future.add_done_callback(self._consume)
        return future

    def call_later(self, delay: float, callback) -> None:  # noqa: ANN001
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(loop.call_later, delay, callback)

    @staticmethod
    def _consume(future) -> None:  # noqa: ANN001
        if future.cancelled():
            return
        try:
            future.result()
        except Exception:
            logger.exception("Unhandled async task error")

    def shutdown(self, timeout: float = 3.0) -> None:
        loop = self.loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self.loop = None


class KatyaApp(ctk.CTk):
    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        super().__init__()

        self.title(config.APP_TITLE)
        self.geometry("1220x800")
        self.minsize(1080, 720)
        self.configure(fg_color=COLORS["bg"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.settings = config.load_settings()
        self._closing = False
        self._shutdown_done = False
        self._current_page = "core"
        self._provider = self.settings.get("provider", config.DEFAULT_PROVIDER)
        self._events: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self._state: dict[str, Any] = {
            "listening": False,
            "thinking": False,
            "speaking": False,
            "coach": False,
            "provider": self._provider,
        }
        self._level = 0.0
        self._phase = 0.0
        self._started_at = time.monotonic()
        self._log_lines = 0
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._cloud_key_entries: dict[str, ctk.CTkEntry] = {}
        self._cloud_model_entries: dict[str, ctk.CTkEntry] = {}
        self._suppress_switch = False

        self.runtime = AsyncRuntime()
        self.runtime.start()
        self.engine = KatyaEngine(self.runtime, self._on_engine_event)

        self._build_layout()
        self._bind_shortcuts()
        self._animate()
        self._tick_clock()
        self._sync_protocol_switches()
        self.after(80, self._poll_events)
        self.after(200, self._start_engine)

    # ==================================================================
    # Layout
    # ==================================================================
    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)

        self._build_sidebar()
        self._build_header()
        self._build_statusbar()

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=1, column=1, sticky="nsew", padx=(10, 18), pady=(8, 8))
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self._build_core_page()
        self._build_neuro_page()
        self._build_protocols_page()
        self._build_log_page()
        self._show_page("core")

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(
            self,
            width=212,
            fg_color=COLORS["panel"],
            corner_radius=0,
            border_width=0,
        )
        sidebar.grid(row=0, column=0, rowspan=3, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(5, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(24, 8))
        ctk.CTkLabel(
            brand,
            text="КАТЯ",
            font=ctk.CTkFont("Segoe UI", 32, "bold"),
            text_color=COLORS["neon"],
            anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            brand,
            text="2.11.0 // SWARM",
            font=ctk.CTkFont("Consolas", 11, "bold"),
            text_color=COLORS["neon_soft"],
            anchor="w",
        ).pack(fill="x")

        line = ctk.CTkFrame(sidebar, height=2, fg_color=COLORS["neon_dim"])
        line.grid(row=1, column=0, sticky="ew", padx=18, pady=(8, 18))

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.grid(row=2, column=0, sticky="ew", padx=12)
        nav.grid_columnconfigure(0, weight=1)
        items = [
            ("core", "◉  ЯДРО"),
            ("neuro", "◇  НЕЙРО-СЕТЬ"),
            ("protocols", "⬡  ПРОТОКОЛЫ"),
            ("log", "▤  ЖУРНАЛ"),
        ]
        for row, (key, label) in enumerate(items):
            button = ctk.CTkButton(
                nav,
                text=label,
                anchor="w",
                height=42,
                corner_radius=8,
                fg_color="transparent",
                hover_color=COLORS["panel3"],
                text_color=COLORS["muted"],
                font=ctk.CTkFont("Segoe UI", 14, "bold"),
                command=lambda page=key: self._show_page(page),
            )
            button.grid(row=row, column=0, sticky="ew", pady=3)
            self._nav_buttons[key] = button

        telemetry = ctk.CTkFrame(
            sidebar,
            fg_color=COLORS["panel2"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["line"],
        )
        telemetry.grid(row=4, column=0, sticky="ew", padx=14, pady=(20, 8))
        ctk.CTkLabel(
            telemetry,
            text="SYSTEM VITALS",
            font=ctk.CTkFont("Consolas", 10, "bold"),
            text_color=COLORS["neon_soft"],
            anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 4))

        self.sidebar_mic = self._sidebar_metric(telemetry, "MIC")
        self.sidebar_brain = self._sidebar_metric(telemetry, "BRAIN")
        self.sidebar_coach = self._sidebar_metric(telemetry, "COACH")
        self.sidebar_echo = self._sidebar_metric(telemetry, "ECHO")

        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=6, column=0, sticky="ew", padx=18, pady=(6, 18))
        self.uptime_label = ctk.CTkLabel(
            footer,
            text="UPTIME 00:00:00",
            font=ctk.CTkFont("Consolas", 10),
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.uptime_label.pack(fill="x")
        ctk.CTkLabel(
            footer,
            text="PUBLIC BUILD // NO TELEMETRY",
            font=ctk.CTkFont("Consolas", 9),
            text_color=COLORS["neon_dim"],
            anchor="w",
        ).pack(fill="x", pady=(3, 0))

    def _sidebar_metric(self, parent, name: str) -> ctk.CTkLabel:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(
            row,
            text=name,
            width=48,
            anchor="w",
            font=ctk.CTkFont("Consolas", 10),
            text_color=COLORS["muted"],
        ).pack(side="left")
        label = ctk.CTkLabel(
            row,
            text="—",
            anchor="e",
            font=ctk.CTkFont("Consolas", 10, "bold"),
            text_color=COLORS["text"],
        )
        label.pack(side="right")
        return label

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent", height=86)
        header.grid(row=0, column=1, sticky="ew", padx=(12, 18), pady=(14, 2))
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)

        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            titles,
            text="MARVEL-SWARM  //  COMMAND DECK",
            font=ctk.CTkFont("Segoe UI", 18, "bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            titles,
            text="ЛОКАЛЬНЫЙ ИИ · ГОЛОС · ROBLOX COACH · WIN32",
            font=ctk.CTkFont("Consolas", 9),
            text_color=COLORS["muted"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        chips = ctk.CTkFrame(header, fg_color="transparent")
        chips.grid(row=0, column=1, sticky="e", padx=(12, 18))
        self.mic_chip = self._chip(chips, "MIC", COLORS["muted"])
        self.brain_chip = self._chip(chips, "BRAIN", COLORS["neon"])
        self.coach_chip = self._chip(chips, "COACH", COLORS["muted"])

        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.grid(row=0, column=2, sticky="e")
        ctk.CTkLabel(
            controls,
            text="МОЗГ",
            font=ctk.CTkFont("Consolas", 8, "bold"),
            text_color=COLORS["neon_soft"],
        ).grid(row=0, column=0, padx=(0, 5))
        self.provider_menu = ctk.CTkOptionMenu(
            controls,
            values=list(LABEL_TO_PROVIDER.keys()),
            width=196,
            height=30,
            corner_radius=7,
            fg_color=COLORS["panel3"],
            button_color=COLORS["neon_dim"],
            button_hover_color=COLORS["neon_soft"],
            dropdown_fg_color=COLORS["panel2"],
            dropdown_hover_color=COLORS["panel3"],
            text_color=COLORS["text"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            command=self._on_provider_menu,
            dynamic_resizing=False,
        )
        self.provider_menu.grid(row=0, column=1, sticky="ew", pady=(0, 5))
        self.provider_menu.set(PROVIDER_LABELS.get(self._provider, "Локальный ИИ"))

        self.header_key_entry = ctk.CTkEntry(
            controls,
            width=170,
            height=30,
            corner_radius=7,
            fg_color=COLORS["panel2"],
            border_color=COLORS["line"],
            text_color=COLORS["text"],
            placeholder_text="API KEY",
            show="•",
            font=ctk.CTkFont("Consolas", 10),
        )
        self.header_key_entry.grid(row=1, column=0, padx=(0, 5))
        self.header_key_entry.bind("<Return>", lambda _event: self._save_header_key())
        self.header_key_button = ctk.CTkButton(
            controls,
            text="SAVE",
            width=60,
            height=30,
            corner_radius=7,
            fg_color=COLORS["neon_dim"],
            hover_color=COLORS["neon_soft"],
            text_color=COLORS["text"],
            font=ctk.CTkFont("Consolas", 9, "bold"),
            command=self._save_header_key,
        )
        self.header_key_button.grid(row=1, column=1)
        self._refresh_header_key()

    def _chip(self, parent, text: str, color: str) -> ctk.CTkLabel:
        frame = ctk.CTkFrame(
            parent,
            fg_color=COLORS["panel2"],
            corner_radius=9,
            border_width=1,
            border_color=COLORS["line"],
        )
        frame.pack(side="left", padx=3)
        label = ctk.CTkLabel(
            frame,
            text=f"● {text}",
            font=ctk.CTkFont("Consolas", 8, "bold"),
            text_color=color,
        )
        label.pack(padx=6, pady=5)
        return label

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(
            self,
            height=38,
            fg_color=COLORS["panel"],
            corner_radius=0,
            border_width=1,
            border_color=COLORS["line"],
        )
        bar.grid(row=2, column=1, sticky="ew", padx=(0, 0))
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)

        self.status_text = ctk.CTkLabel(
            bar,
            text="Инициализация…",
            font=ctk.CTkFont("Consolas", 10),
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.status_text.grid(row=0, column=0, sticky="w", padx=16, pady=8)

        self.progress = ctk.CTkProgressBar(
            bar,
            width=150,
            height=5,
            corner_radius=3,
            fg_color=COLORS["panel3"],
            progress_color=COLORS["neon"],
        )
        self.progress.set(0)
        self.progress.grid(row=0, column=1, padx=10)
        self.progress.grid_remove()

        self.clock_label = ctk.CTkLabel(
            bar,
            text="--:--:--",
            font=ctk.CTkFont("Consolas", 10, "bold"),
            text_color=COLORS["neon_soft"],
        )
        self.clock_label.grid(row=0, column=2, padx=16)

    # ==================================================================
    # Pages
    # ==================================================================
    def _new_page(self, name: str) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()
        self._pages[name] = page
        return page

    def _build_core_page(self) -> None:
        page = self._new_page("core")
        page.grid_columnconfigure(0, weight=3)
        page.grid_columnconfigure(1, weight=2)
        page.grid_rowconfigure(0, weight=1)

        left = self._card(page)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(left, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        ctk.CTkLabel(
            head,
            text="НЕЙРО-ЯДРО",
            font=ctk.CTkFont("Consolas", 11, "bold"),
            text_color=COLORS["neon_soft"],
        ).pack(side="left")
        self.core_state_label = ctk.CTkLabel(
            head,
            text="· ОЖИДАНИЕ",
            font=ctk.CTkFont("Consolas", 10, "bold"),
            text_color=COLORS["muted"],
        )
        self.core_state_label.pack(side="right")

        canvas_frame = ctk.CTkFrame(left, fg_color=COLORS["panel"], corner_radius=0)
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)
        self.orb = tk.Canvas(
            canvas_frame,
            bg=COLORS["panel"],
            highlightthickness=0,
            bd=0,
        )
        self.orb.grid(row=0, column=0, sticky="nsew")
        self.orb.bind("<Configure>", self._on_orb_resize)

        command = ctk.CTkFrame(left, fg_color="transparent")
        command.grid(row=2, column=0, sticky="ew", padx=14, pady=(2, 14))
        command.grid_columnconfigure(0, weight=1)
        self.command_entry = ctk.CTkEntry(
            command,
            height=40,
            corner_radius=10,
            fg_color=COLORS["panel2"],
            border_color=COLORS["line"],
            text_color=COLORS["text"],
            placeholder_text="Команда или вопрос Кате…",
            font=ctk.CTkFont("Segoe UI", 13),
        )
        self.command_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.command_entry.bind("<Return>", lambda _event: self._send_command())
        ctk.CTkButton(
            command,
            text="→",
            width=46,
            height=40,
            corner_radius=10,
            fg_color=COLORS["neon_dim"],
            hover_color=COLORS["neon_soft"],
            text_color=COLORS["text"],
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
            command=self._send_command,
        ).grid(row=0, column=1, padx=(0, 6))
        self.listen_button = ctk.CTkButton(
            command,
            text="MIC",
            width=60,
            height=40,
            corner_radius=10,
            fg_color=COLORS["panel3"],
            hover_color=COLORS["neon_dim"],
            text_color=COLORS["text"],
            font=ctk.CTkFont("Consolas", 10, "bold"),
            command=self._toggle_mic,
        )
        self.listen_button.grid(row=0, column=2)

        right = ctk.CTkFrame(page, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=3)
        right.grid_rowconfigure(1, weight=2)

        chat_card = self._card(right)
        chat_card.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        chat_card.grid_columnconfigure(0, weight=1)
        chat_card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            chat_card,
            text="ДИАЛОГ // LIVE",
            font=ctk.CTkFont("Consolas", 11, "bold"),
            text_color=COLORS["neon_soft"],
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))

        chat_wrap = ctk.CTkFrame(chat_card, fg_color=COLORS["panel"], corner_radius=0)
        chat_wrap.grid(row=1, column=0, sticky="nsew", padx=(10, 4), pady=(0, 6))
        chat_wrap.grid_rowconfigure(0, weight=1)
        chat_wrap.grid_columnconfigure(0, weight=1)
        self.chat_box = tk.Text(
            chat_wrap,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            insertbackground=COLORS["neon"],
            selectbackground=COLORS["neon_dim"],
            font=("Consolas", 10),
            relief="flat",
            bd=0,
            wrap="word",
            padx=10,
            pady=6,
            state="disabled",
        )
        self.chat_box.grid(row=0, column=0, sticky="nsew")
        self.chat_scroll = ctk.CTkScrollbar(
            chat_wrap,
            command=self.chat_box.yview,
            width=10,
            fg_color=COLORS["panel"],
            button_color=COLORS["neon_dim"],
            button_hover_color=COLORS["neon_soft"],
        )
        self.chat_scroll.grid(row=0, column=1, sticky="ns", padx=(3, 0))
        self.chat_box.configure(yscrollcommand=self.chat_scroll.set)
        self.chat_box.tag_config("user", foreground=COLORS["neon"])
        self.chat_box.tag_config("assistant", foreground=COLORS["text"])
        self.chat_box.tag_config("system", foreground=COLORS["warn"])
        self.chat_box.tag_config("meta", foreground=COLORS["muted"])

        partial_row = ctk.CTkFrame(chat_card, fg_color="transparent")
        partial_row.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
        self.partial_label = ctk.CTkLabel(
            partial_row,
            text="",
            font=ctk.CTkFont("Consolas", 9),
            text_color=COLORS["neon_dim"],
            anchor="w",
            wraplength=300,
        )
        self.partial_label.pack(fill="x")

        telemetry = self._card(right)
        telemetry.grid(row=1, column=0, sticky="nsew")
        telemetry.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            telemetry,
            text="ТЕЛЕМЕТРИЯ",
            font=ctk.CTkFont("Consolas", 11, "bold"),
            text_color=COLORS["neon_soft"],
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(10, 6))

        self.telemetry_values: dict[str, ctk.CTkLabel] = {}
        rows = [
            ("provider", "ПРОВАЙДЕР"),
            ("model", "МОДЕЛЬ"),
            ("mic", "МИКРОФОН"),
            ("echo", "ECHO GUARD"),
            ("coach", "CYBER-COACH"),
            ("uptime", "СЕССИЯ"),
        ]
        for index, (key, label) in enumerate(rows, start=1):
            ctk.CTkLabel(
                telemetry,
                text=label,
                font=ctk.CTkFont("Consolas", 9),
                text_color=COLORS["muted"],
                anchor="w",
            ).grid(row=index, column=0, sticky="w", padx=14, pady=2)
            value = ctk.CTkLabel(
                telemetry,
                text="—",
                font=ctk.CTkFont("Consolas", 9, "bold"),
                text_color=COLORS["text"],
                anchor="e",
            )
            value.grid(row=index, column=1, sticky="e", padx=14, pady=2)
            self.telemetry_values[key] = value

        actions = ctk.CTkFrame(telemetry, fg_color="transparent")
        actions.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 4))
        ctk.CTkButton(
            actions,
            text="ПРЕРВАТЬ ГОЛОС",
            height=28,
            fg_color=COLORS["panel3"],
            hover_color=COLORS["neon_dim"],
            text_color=COLORS["muted"],
            font=ctk.CTkFont("Consolas", 9, "bold"),
            command=self.engine.interrupt_speech,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            actions,
            text="СБРОС КОНТЕКСТА",
            height=28,
            fg_color=COLORS["panel3"],
            hover_color=COLORS["neon_dim"],
            text_color=COLORS["muted"],
            font=ctk.CTkFont("Consolas", 9, "bold"),
            command=self.engine.clear_memory,
        ).pack(side="left", padx=2)

    def _build_neuro_page(self) -> None:
        page = self._new_page("neuro")
        page.grid_columnconfigure(0, weight=1)
        page.grid_columnconfigure(1, weight=1)
        page.grid_columnconfigure(2, weight=1)
        page.grid_rowconfigure(1, weight=1)

        intro = ctk.CTkFrame(page, fg_color="transparent")
        intro.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(
            intro,
            text="НЕЙРО-СЕТЬ",
            font=ctk.CTkFont("Segoe UI", 18, "bold"),
            text_color=COLORS["text"],
        ).pack(side="left")
        ctk.CTkLabel(
            intro,
            text="КЛЮЧИ ЛОКАЛЬНО · settings.json",
            font=ctk.CTkFont("Consolas", 8),
            text_color=COLORS["muted"],
        ).pack(side="left", padx=(14, 0), pady=(5, 0))

        local = self._card(page)
        local.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        local.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            local,
            text="OLLAMA // LOCAL CORE",
            font=ctk.CTkFont("Consolas", 11, "bold"),
            text_color=COLORS["neon"],
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 2))
        ctk.CTkLabel(
            local,
            text=config.OLLAMA_URL,
            font=ctk.CTkFont("Consolas", 9),
            text_color=COLORS["muted"],
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))

        ctk.CTkLabel(
            local,
            text=(
                f"{config.MODEL_FAST}\n"
                f"{config.MODEL_LIGHT}\n"
                f"{config.MODEL_VISION}"
            ),
            font=ctk.CTkFont("Consolas", 9),
            text_color=COLORS["text"],
            anchor="w",
            justify="left",
        ).grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 10))

        ctk.CTkLabel(
            local,
            text="ОСНОВНАЯ МОДЕЛЬ",
            font=ctk.CTkFont("Consolas", 9, "bold"),
            text_color=COLORS["neon_soft"],
            anchor="w",
        ).grid(row=3, column=0, sticky="ew", padx=14)
        self.local_model_entry = self._entry(local)
        self.local_model_entry.grid(row=4, column=0, sticky="ew", padx=14, pady=(3, 8))
        self.local_model_entry.insert(
            0,
            str(self.settings.get("models", {}).get("local", config.MODEL_FAST)),
        )

        row = ctk.CTkFrame(local, fg_color="transparent")
        row.grid(row=5, column=0, sticky="ew", padx=12, pady=(2, 12))
        ctk.CTkButton(
            row,
            text="ПРИМЕНИТЬ",
            width=108,
            height=30,
            fg_color=COLORS["neon_dim"],
            hover_color=COLORS["neon_soft"],
            text_color=COLORS["text"],
            font=ctk.CTkFont("Consolas", 9, "bold"),
            command=self._apply_local_model,
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            row,
            text="OLLAMA",
            width=70,
            height=30,
            fg_color=COLORS["panel3"],
            hover_color=COLORS["neon_dim"],
            text_color=COLORS["muted"],
            font=ctk.CTkFont("Consolas", 9, "bold"),
            command=lambda: self.engine.probe_provider("local"),
        ).pack(side="left", padx=3)

        for index, provider in enumerate(("claude", "chatgpt", "deepseek"), start=1):
            self._build_cloud_card(page, provider, index)

    def _build_cloud_card(self, parent, provider: str, column: int) -> None:
        name = PROVIDER_LABELS[provider]
        card = self._card(parent)
        card.grid(row=1, column=column, sticky="nsew", padx=(6, 0) if column == 2 else (6, 6))
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=f"{name.upper()} // CLOUD",
            font=ctk.CTkFont("Consolas", 11, "bold"),
            text_color=COLORS["neon"],
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 10))

        ctk.CTkLabel(
            card,
            text="МОДЕЛЬ",
            font=ctk.CTkFont("Consolas", 9, "bold"),
            text_color=COLORS["neon_soft"],
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=14)
        model_entry = self._entry(card)
        model_entry.grid(row=2, column=0, sticky="ew", padx=14, pady=(3, 8))
        model_entry.insert(
            0,
            str(self.settings.get("models", {}).get(provider, config.PROVIDERS[provider]["model"])),
        )
        self._cloud_model_entries[provider] = model_entry

        ctk.CTkLabel(
            card,
            text="API KEY",
            font=ctk.CTkFont("Consolas", 9, "bold"),
            text_color=COLORS["neon_soft"],
            anchor="w",
        ).grid(row=3, column=0, sticky="ew", padx=14)
        key_entry = self._entry(card, show="•")
        key_entry.grid(row=4, column=0, sticky="ew", padx=14, pady=(3, 6))
        key_entry.insert(0, config.get_api_key(provider))
        self._cloud_key_entries[provider] = key_entry

        note = ctk.CTkLabel(
            card,
            text="Ключ не попадает в Git и логи.",
            font=ctk.CTkFont("Consolas", 8),
            text_color=COLORS["muted"],
            anchor="w",
        )
        note.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 8))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=6, column=0, sticky="ew", padx=12, pady=(0, 12))
        ctk.CTkButton(
            row,
            text="СОХРАНИТЬ",
            width=106,
            height=30,
            fg_color=COLORS["neon_dim"],
            hover_color=COLORS["neon_soft"],
            text_color=COLORS["text"],
            font=ctk.CTkFont("Consolas", 8, "bold"),
            command=lambda p=provider: self._save_cloud_key(p),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            row,
            text="ТЕСТ",
            width=58,
            height=30,
            fg_color=COLORS["panel3"],
            hover_color=COLORS["neon_dim"],
            text_color=COLORS["muted"],
            font=ctk.CTkFont("Consolas", 8, "bold"),
            command=lambda p=provider: self.engine.probe_provider(p),
        ).pack(side="left", padx=3)

    def _build_protocols_page(self) -> None:
        page = self._new_page("protocols")
        page.grid_columnconfigure(0, weight=1)
        page.grid_columnconfigure(1, weight=1)
        page.grid_rowconfigure(1, weight=1)

        intro = ctk.CTkFrame(page, fg_color="transparent")
        intro.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(
            intro,
            text="MARVEL PROTOCOLS",
            font=ctk.CTkFont("Segoe UI", 18, "bold"),
            text_color=COLORS["text"],
        ).pack(side="left")
        ctk.CTkLabel(
            intro,
            text="  все изменения обратимы и снимаются при выходе",
            font=ctk.CTkFont("Consolas", 9),
            text_color=COLORS["muted"],
        ).pack(side="left", pady=(5, 0))

        coach = self._protocol_card(
            page,
            1,
            0,
            "CYBER-COACH",
            "Roblox · llava · кадр раз в 3 секунды\n"
            "Анализ кулдаунов и комбо для Тени / Воина.\n"
            "Захват только активного окна Roblox.",
            COLORS["neon"],
        )
        self.coach_switch = ctk.CTkSwitch(
            coach,
            text="АКТИВЕН",
            font=ctk.CTkFont("Consolas", 9, "bold"),
            progress_color=COLORS["neon"],
            button_color=COLORS["text"],
            button_hover_color=COLORS["neon"],
            text_color=COLORS["muted"],
            command=self._toggle_coach,
        )
        self.coach_switch.pack(anchor="w", padx=16, pady=(2, 6))
        self.coach_status_label = ctk.CTkLabel(
            coach,
            text="Выключен. Включи только там, где это разрешено.",
            font=ctk.CTkFont("Consolas", 8),
            text_color=COLORS["muted"],
            anchor="w",
            wraplength=420,
            justify="left",
        )
        self.coach_status_label.pack(fill="x", padx=16, pady=(0, 12))

        overclock = self._protocol_card(
            page,
            1,
            1,
            "МАКСИМАЛЬНЫЙ OVERCLOCK",
            "High-performance power plan + HIGH_PRIORITY_CLASS\n"
            "для Roblox. Предыдущая схема питания и приоритеты\n"
            "восстанавливаются при снятии протокола.",
            COLORS["warn"],
        )
        self.overclock_switch = ctk.CTkSwitch(
            overclock,
            text="БУСТ FPS",
            font=ctk.CTkFont("Consolas", 9, "bold"),
            progress_color=COLORS["warn"],
            button_color=COLORS["text"],
            button_hover_color=COLORS["warn"],
            text_color=COLORS["muted"],
            command=self._toggle_overclock,
        )
        self.overclock_switch.pack(anchor="w", padx=16, pady=(2, 6))
        self.overclock_status_label = ctk.CTkLabel(
            overclock,
            text="Не активен.",
            font=ctk.CTkFont("Consolas", 8),
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.overclock_status_label.pack(fill="x", padx=16, pady=(0, 12))

        boss = self._protocol_card(
            page,
            2,
            0,
            "СПРЯЧЬ ПАЛЕВО",
            "Ctrl+Shift+H — скрыть Roblox/браузер и замьютить\n"
            "все аудиосессии. Повторное нажатие возвращает окна\n"
            "и громкость. Работает и с кнопки ниже.",
            COLORS["error"],
        )
        self.boss_switch = ctk.CTkSwitch(
            boss,
            text="BOSS MODE",
            font=ctk.CTkFont("Consolas", 9, "bold"),
            progress_color=COLORS["error"],
            button_color=COLORS["text"],
            button_hover_color=COLORS["error"],
            text_color=COLORS["muted"],
            command=self._toggle_boss,
        )
        self.boss_switch.pack(anchor="w", padx=16, pady=(2, 6))
        self.boss_status_label = ctk.CTkLabel(
            boss,
            text="Горячая клавиша: Ctrl+Shift+H",
            font=ctk.CTkFont("Consolas", 8),
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.boss_status_label.pack(fill="x", padx=16, pady=(0, 12))

        evolution = self._protocol_card(
            page,
            2,
            1,
            "RUNTIME SELF-EVOLUTION",
            "Горячая замена allow-listed модулей через importlib.\n"
            "Каждый патч: backup → compile → reload → rollback.\n"
            "LLM-патчи применяются только с явным approved=True.",
            COLORS["ok"],
        )
        ctk.CTkButton(
            evolution,
            text="ЗАПУСТИТЬ SELF-HEALING",
            height=32,
            fg_color=COLORS["panel3"],
            hover_color=COLORS["neon_dim"],
            text_color=COLORS["text"],
            font=ctk.CTkFont("Consolas", 9, "bold"),
            command=self.engine.self_heal,
        ).pack(anchor="w", padx=16, pady=(4, 4))
        ctk.CTkLabel(
            evolution,
            text="Проверка импортов · авто-откат · резервные копии",
            font=ctk.CTkFont("Consolas", 8),
            text_color=COLORS["muted"],
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 12))

    def _protocol_card(
        self,
        parent,
        row: int,
        column: int,
        title: str,
        description: str,
        accent: str,
    ) -> ctk.CTkFrame:
        card = self._card(parent)
        card.grid(
            row=row,
            column=column,
            sticky="nsew",
            padx=(0, 6) if column == 0 else (6, 0),
            pady=(0, 8) if row == 1 else (0, 0),
        )
        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont("Segoe UI", 15, "bold"),
            text_color=accent,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            card,
            text=description,
            font=ctk.CTkFont("Consolas", 9),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=430,
        ).pack(fill="x", padx=16, pady=(0, 10))
        return card

    def _build_log_page(self) -> None:
        page = self._new_page("log")
        page.grid_rowconfigure(1, weight=1)
        page.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(page, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(
            head,
            text="ЖУРНАЛ // SYSTEM LOG",
            font=ctk.CTkFont("Segoe UI", 18, "bold"),
            text_color=COLORS["text"],
        ).pack(side="left")
        ctk.CTkButton(
            head,
            text="ЭКСПОРТ",
            width=86,
            height=28,
            fg_color=COLORS["panel3"],
            hover_color=COLORS["neon_dim"],
            text_color=COLORS["muted"],
            font=ctk.CTkFont("Consolas", 9, "bold"),
            command=self._export_log,
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            head,
            text="ОЧИСТИТЬ",
            width=86,
            height=28,
            fg_color=COLORS["panel3"],
            hover_color=COLORS["neon_dim"],
            text_color=COLORS["muted"],
            font=ctk.CTkFont("Consolas", 9, "bold"),
            command=self._clear_log,
        ).pack(side="right", padx=4)

        card = self._card(page)
        card.grid(row=1, column=0, sticky="nsew")
        card.grid_rowconfigure(0, weight=1)
        card.grid_columnconfigure(0, weight=1)
        log_wrap = ctk.CTkFrame(card, fg_color=COLORS["panel"], corner_radius=0)
        log_wrap.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        log_wrap.grid_rowconfigure(0, weight=1)
        log_wrap.grid_columnconfigure(0, weight=1)
        self.log_box = tk.Text(
            log_wrap,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            insertbackground=COLORS["neon"],
            selectbackground=COLORS["neon_dim"],
            font=("Consolas", 10),
            relief="flat",
            bd=0,
            wrap="word",
            padx=12,
            pady=8,
            state="disabled",
        )
        self.log_box.grid(row=0, column=0, sticky="nsew")
        self.log_scroll = ctk.CTkScrollbar(
            log_wrap,
            command=self.log_box.yview,
            width=10,
            fg_color=COLORS["panel"],
            button_color=COLORS["neon_dim"],
            button_hover_color=COLORS["neon_soft"],
        )
        self.log_scroll.grid(row=0, column=1, sticky="ns", padx=(3, 0))
        self.log_box.configure(yscrollcommand=self.log_scroll.set)
        self.log_box.tag_config("info", foreground=COLORS["text"])
        self.log_box.tag_config("ok", foreground=COLORS["ok"])
        self.log_box.tag_config("warn", foreground=COLORS["warn"])
        self.log_box.tag_config("error", foreground=COLORS["error"])
        self.log_box.tag_config("time", foreground=COLORS["neon_dim"])

    def _card(self, parent) -> ctk.CTkFrame:
        return ctk.CTkFrame(
            parent,
            fg_color=COLORS["panel"],
            corner_radius=14,
            border_width=1,
            border_color=COLORS["line"],
        )

    @staticmethod
    def _entry(parent, show: str = "") -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent,
            height=32,
            corner_radius=7,
            fg_color=COLORS["panel2"],
            border_color=COLORS["line"],
            text_color=COLORS["text"],
            show=show,
            font=("Consolas", 10),
        )

    # ==================================================================
    # Navigation / actions
    # ==================================================================
    def _show_page(self, name: str) -> None:
        if name not in self._pages:
            return
        self._current_page = name
        for key, page in self._pages.items():
            if key == name:
                page.grid()
            else:
                page.grid_remove()
        for key, button in self._nav_buttons.items():
            if key == name:
                button.configure(
                    fg_color=COLORS["panel3"],
                    text_color=COLORS["neon"],
                )
            else:
                button.configure(
                    fg_color="transparent",
                    text_color=COLORS["muted"],
                )

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-space>", lambda _event: self.engine.interrupt_speech())
        self.bind("<Control-l>", lambda _event: self._show_page("log"))
        self.bind("<Control-Return>", lambda _event: self._send_command())

    def _start_engine(self) -> None:
        if self._closing:
            return
        self.engine.start()
        self.status_text.configure(text="ЯДРО АКТИВНО // ИНИЦИАЛИЗАЦИЯ ГОЛОСОВОГО КАНАЛА")
        self._append_chat(
            "system",
            "Marvel-Swarm ONLINE. Ядро 2.11.0 готово. "
            "Говори или введи команду в строке ниже.",
        )
        self._append_log("HUD запущен. Постоянное прослушивание инициализируется.", "ok")

    def _send_command(self) -> None:
        text = self.command_entry.get().strip()
        if not text:
            return
        self.command_entry.delete(0, "end")
        self.engine.ask(text)
        self._append_log(f"Команда: {text}", "info")

    def _toggle_mic(self) -> None:
        self.engine.toggle_listening()
        self._append_log("Переключение микрофона.", "info")

    def _on_provider_menu(self, label: str) -> None:
        provider = LABEL_TO_PROVIDER.get(label)
        if not provider or provider == self._provider:
            return
        self._provider = provider
        self.engine.set_provider(provider)
        self._refresh_header_key()
        self._apply_state({"provider": provider})
        self._append_log(f"Провайдер: {label}", "info")

    def _refresh_header_key(self) -> None:
        self.header_key_entry.configure(state="normal")
        self.header_key_entry.delete(0, "end")
        if self._provider == "local":
            self.header_key_entry.configure(
                state="disabled",
                placeholder_text="НЕ ТРЕБУЕТСЯ",
            )
            self.header_key_button.configure(state="disabled")
        else:
            self.header_key_entry.configure(placeholder_text="API KEY")
            key = config.get_api_key(self._provider)
            if key:
                self.header_key_entry.insert(0, key)
            self.header_key_button.configure(state="normal")
        self.provider_menu.set(PROVIDER_LABELS.get(self._provider, "Локальный ИИ"))

    def _save_header_key(self) -> None:
        if self._provider == "local":
            return
        key = self.header_key_entry.get().strip()
        self.engine.save_api_key(self._provider, key)
        self._append_log(
            f"Ключ {PROVIDER_LABELS[self._provider]}: "
            + ("сохранён" if key else "удалён"),
            "ok" if key else "warn",
        )

    def _save_cloud_key(self, provider: str) -> None:
        entry = self._cloud_key_entries.get(provider)
        if entry is None:
            return
        key = entry.get().strip()
        self.engine.save_api_key(provider, key)
        self._append_log(
            f"Ключ {PROVIDER_LABELS[provider]}: "
            + ("сохранён" if key else "удалён"),
            "ok" if key else "warn",
        )

    def _apply_local_model(self) -> None:
        model = self.local_model_entry.get().strip()
        if model:
            self.engine.set_model("local", model)
            self.telemetry_values["model"].configure(text=model)

    def _toggle_coach(self) -> None:
        if self._suppress_switch:
            return
        self.engine.toggle_coach()

    def _toggle_overclock(self) -> None:
        if self._suppress_switch:
            return
        self.engine.toggle_overclock()

    def _toggle_boss(self) -> None:
        if self._suppress_switch:
            return
        self.engine.toggle_boss()

    # ==================================================================
    # Events
    # ==================================================================
    def _on_engine_event(self, kind: str, payload: dict[str, Any]) -> None:
        self._events.put((kind, payload))

    def _poll_events(self) -> None:
        if self._shutdown_done:
            return
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "__shutdown_done__":
                    self._shutdown_done = True
                    self.destroy()
                    return
                self._handle_event(kind, payload)
        except queue.Empty:
            pass
        if not self._shutdown_done:
            self.after(70, self._poll_events)

    def _handle_event(self, kind: str, payload: dict[str, Any]) -> None:
        if kind == "log":
            self._append_log(
                str(payload.get("message", "")),
                str(payload.get("level", "info")),
            )
        elif kind == "state":
            self._apply_state(payload)
        elif kind == "partial":
            text = str(payload.get("text", ""))
            self.partial_label.configure(text=f"… {text}")
        elif kind == "transcript":
            role = str(payload.get("role", "assistant"))
            text = str(payload.get("text", ""))
            self._append_chat(role, text)
            self.partial_label.configure(text="")
        elif kind == "level":
            self._level = float(payload.get("value", 0.0))
        elif kind == "progress":
            value = min(1.0, max(0.0, float(payload.get("value", 0.0))))
            self.progress.grid()
            self.progress.set(value)
            self.status_text.configure(text=str(payload.get("message", "")))
            if value >= 1.0:
                self.after(1800, self._hide_progress)
        elif kind == "coach_status":
            message = str(payload.get("message", ""))
            self.coach_status_label.configure(text=message)
            self._append_log(message, "info")
        elif kind == "tts_status":
            self.status_text.configure(text=str(payload.get("message", "")))
        elif kind == "protocols":
            self._sync_protocol_switches()

    def _hide_progress(self) -> None:
        if not self._closing:
            self.progress.grid_remove()

    def _apply_state(self, state: dict[str, Any]) -> None:
        self._state.update(state)
        listening = bool(self._state.get("listening"))
        thinking = bool(self._state.get("thinking"))
        speaking = bool(self._state.get("speaking"))
        coach = bool(self._state.get("coach"))
        provider = str(self._state.get("provider", self._provider))
        model = str(
            config.load_settings()
            .get("models", {})
            .get(provider, config.PROVIDERS.get(provider, {}).get("model", "—"))
        )

        mic_text = "● MIC ONLINE" if listening else "● MIC OFFLINE"
        self.mic_chip.configure(
            text=mic_text,
            text_color=COLORS["ok"] if listening else COLORS["error"],
        )
        self.sidebar_mic.configure(
            text="ONLINE" if listening else "OFF",
            text_color=COLORS["ok"] if listening else COLORS["error"],
        )
        self.brain_chip.configure(
            text=f"● {PROVIDER_LABELS.get(provider, provider).upper()}",
            text_color=COLORS["neon"],
        )
        self.sidebar_brain.configure(
            text=PROVIDER_LABELS.get(provider, provider),
            text_color=COLORS["neon"],
        )
        self.coach_chip.configure(
            text="● COACH ON" if coach else "● COACH OFF",
            text_color=COLORS["warn"] if coach else COLORS["muted"],
        )
        self.sidebar_coach.configure(
            text="ON" if coach else "OFF",
            text_color=COLORS["warn"] if coach else COLORS["muted"],
        )

        if thinking:
            core_text, core_color = "· АНАЛИЗ", COLORS["warn"]
        elif speaking:
            core_text, core_color = "· ГОЛОС", COLORS["neon"]
        elif listening:
            core_text, core_color = "· ОНЛАЙН", COLORS["ok"]
        else:
            core_text, core_color = "· ОЖИДАНИЕ", COLORS["muted"]
        self.core_state_label.configure(text=core_text, text_color=core_color)

        self.telemetry_values["provider"].configure(
            text=PROVIDER_LABELS.get(provider, provider)
        )
        self.telemetry_values["model"].configure(text=model)
        self.telemetry_values["mic"].configure(
            text="ONLINE" if listening else "OFFLINE",
            text_color=COLORS["ok"] if listening else COLORS["error"],
        )
        echo_active = not thinking and not speaking
        self.telemetry_values["echo"].configure(
            text="ARMED" if echo_active else "GATED",
            text_color=COLORS["ok"] if echo_active else COLORS["warn"],
        )
        self.telemetry_values["coach"].configure(
            text="ACTIVE" if coach else "STANDBY",
            text_color=COLORS["warn"] if coach else COLORS["muted"],
        )
        self.listen_button.configure(
            text="MIC ON" if listening else "MIC OFF",
            fg_color=COLORS["neon_dim"] if listening else COLORS["panel3"],
        )
        if thinking:
            self.status_text.configure(text="НЕЙРО-ЯДРО // АНАЛИЗ ЗАПРОСА")
        elif speaking:
            self.status_text.configure(text="ГОЛОСОВОЙ КАНАЛ // СИНТЕЗ")
        elif listening:
            self.status_text.configure(text="ГОЛОСОВОЙ КАНАЛ АКТИВЕН // MIC ONLINE")
        else:
            self.status_text.configure(text="МИКРОФОН НЕДОСТУПЕН // ПРОВЕРЬТЕ УСТРОЙСТВО")

        if provider != self._provider:
            self._provider = provider
            self._refresh_header_key()

    def _sync_protocol_switches(self) -> None:
        if self._closing:
            return
        try:
            status = self.engine.protocols.status()
        except Exception:
            return
        self._suppress_switch = True
        try:
            if self.engine.coach.running:
                self.coach_switch.select()
            else:
                self.coach_switch.deselect()
            if status["overclock"]["active"]:
                self.overclock_switch.select()
                self.overclock_status_label.configure(
                    text=f"Boost: {status['overclock']['boosted_processes']} процессов",
                    text_color=COLORS["warn"],
                )
            else:
                self.overclock_switch.deselect()
                self.overclock_status_label.configure(
                    text="Не активен.", text_color=COLORS["muted"]
                )
            if status["boss"]["active"]:
                self.boss_switch.select()
                self.boss_status_label.configure(
                    text=f"Скрыто {status['boss']['hidden_windows']} окон · "
                    f"замьючено {status['boss']['muted_sessions']}",
                    text_color=COLORS["error"],
                )
            else:
                self.boss_switch.deselect()
                self.boss_status_label.configure(
                    text="Горячая клавиша: Ctrl+Shift+H",
                    text_color=COLORS["muted"],
                )
        finally:
            self._suppress_switch = False

        if getattr(self, "coach_status_label", None) is not None:
            last = self.engine.coach.status.last_advice
            if last and self.engine.coach.running:
                self.coach_status_label.configure(
                    text=f"Последний совет: {last}",
                    text_color=COLORS["text"],
                )
        if not self._closing:
            self.after(900, self._sync_protocol_switches)

    # ==================================================================
    # Text / clock
    # ==================================================================
    def _append_log(self, message: str, level: str = "info") -> None:
        if not message:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{timestamp}] ", "time")
        self.log_box.insert("end", f"{message}\n", level if level in ("ok", "warn", "error") else "info")
        self.log_box.see("end")
        self.log_lines_count()
        self.log_box.configure(state="disabled")
        logger.info(message)

    def log_lines_count(self) -> None:
        self._log_lines += 1
        if self._log_lines > 1200:
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "300.0")
            self.log_box.configure(state="disabled")
            self._log_lines -= 299

    def _append_chat(self, role: str, text: str) -> None:
        self.chat_box.configure(state="normal")
        if role == "user":
            prefix, tag = "ТЫ  // ", "user"
        elif role == "system":
            prefix, tag = "СИСТЕМА // ", "system"
        else:
            prefix, tag = "КАТЯ // ", "assistant"
        self.chat_box.insert("end", prefix, "meta")
        self.chat_box.insert("end", f"{text}\n\n", tag)
        self.chat_box.see("end")
        self.chat_box.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._log_lines = 0

    def _export_log(self) -> None:
        path = config.LOG_DIR / f"katya_ui_{datetime.now():%Y%m%d_%H%M%S}.log"
        try:
            path.write_text(self.log_box.get("1.0", "end"), encoding="utf-8")
            self._append_log(f"Журнал сохранён: {path}", "ok")
        except OSError as exc:
            self._append_log(f"Не удалось сохранить журнал: {exc}", "error")

    def _tick_clock(self) -> None:
        if self._closing:
            return
        self.clock_label.configure(text=datetime.now().strftime("%H:%M:%S"))
        elapsed = int(time.monotonic() - self._started_at)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        self.uptime_label.configure(text=f"UPTIME {uptime}")
        self.telemetry_values["uptime"].configure(text=uptime)
        self.sidebar_echo.configure(
            text="ARMED" if not self._state.get("speaking") else "GATED",
            text_color=COLORS["ok"] if not self._state.get("speaking") else COLORS["warn"],
        )
        self.after(1000, self._tick_clock)

    # ==================================================================
    # HUD animation
    # ==================================================================
    def _on_orb_resize(self, _event=None) -> None:  # noqa: ANN001
        self._draw_orb(force=True)

    def _animate(self) -> None:
        if self._closing:
            return
        self._phase += 0.055
        self._level *= 0.90
        self._draw_orb()
        self.after(45, self._animate)

    def _draw_orb(self, force: bool = False) -> None:
        if not hasattr(self, "orb"):
            return
        width = self.orb.winfo_width()
        height = self.orb.winfo_height()
        if width < 80 or height < 80:
            return

        self.orb.delete("dynamic")
        cx, cy = width / 2, height / 2
        radius = min(width, height) * 0.31
        level = max(0.0, min(1.0, self._level))
        thinking = bool(self._state.get("thinking"))
        speaking = bool(self._state.get("speaking"))
        active = thinking or speaking

        # outer orbit ticks
        for index in range(72):
            angle = math.radians(index * 5 + self._phase * 4)
            inner = radius * 1.36
            pulse = 0.5 + 0.5 * math.sin(self._phase * 2.1 + index * 0.35)
            outer = inner + 3 + pulse * 5 + (7 if speaking else 0)
            color = COLORS["neon"] if index % 6 == 0 else COLORS["neon_dim"]
            self.orb.create_line(
                cx + math.cos(angle) * inner,
                cy + math.sin(angle) * inner,
                cx + math.cos(angle) * outer,
                cy + math.sin(angle) * outer,
                fill=color,
                width=1,
                tags="dynamic",
            )

        # concentric rings
        for factor, color, width_px in (
            (1.30, COLORS["neon_dim"], 1),
            (1.00, COLORS["line"], 1),
            (0.78, COLORS["neon_dim"], 1),
            (0.54, COLORS["line"], 1),
        ):
            self.orb.create_oval(
                cx - radius * factor,
                cy - radius * factor,
                cx + radius * factor,
                cy + radius * factor,
                outline=color,
                width=width_px,
                tags="dynamic",
            )

        # rotating arcs
        arc_specs = [
            (1.22, 46, 0.9, COLORS["neon"]),
            (1.08, 72, -1.4, COLORS["neon_soft"]),
            (0.88, 34, 1.8, COLORS["neon_dim"]),
        ]
        for factor, extent, speed, color in arc_specs:
            start = (self._phase * 35 * speed) % 360
            self.orb.create_arc(
                cx - radius * factor,
                cy - radius * factor,
                cx + radius * factor,
                cy + radius * factor,
                start=start,
                extent=extent,
                style="arc",
                outline=color,
                width=2,
                tags="dynamic",
            )
            self.orb.create_arc(
                cx - radius * factor - 2,
                cy - radius * factor - 2,
                cx + radius * factor + 2,
                cy + radius * factor + 2,
                start=start + 6,
                extent=max(4, extent - 12),
                style="arc",
                outline=COLORS["neon_dim"],
                width=1,
                tags="dynamic",
            )

        # radial spectrum
        bars = 48
        for index in range(bars):
            angle = math.radians(index * (360 / bars) - 90)
            modulation = 0.35 + 0.65 * abs(
                math.sin(self._phase * 2.0 + index * 0.53)
            )
            length = 2 + level * 38 * modulation + (4 if active else 0)
            inner = radius * 0.56
            color = COLORS["neon"] if level > 0.35 else COLORS["neon_dim"]
            self.orb.create_line(
                cx + math.cos(angle) * inner,
                cy + math.sin(angle) * inner,
                cx + math.cos(angle) * (inner + length),
                cy + math.sin(angle) * (inner + length),
                fill=color,
                width=2,
                tags="dynamic",
            )

        # sweep line
        sweep = (self._phase * 42) % 360
        self.orb.create_arc(
            cx - radius * 1.32,
            cy - radius * 1.32,
            cx + radius * 1.32,
            cy + radius * 1.32,
            start=sweep,
            extent=22,
            style="arc",
            outline=COLORS["neon"],
            width=2,
            tags="dynamic",
        )

        # core glow — hollow rings keep the callsign readable
        core = radius * (0.28 + level * 0.06 + (0.02 if active else 0))
        for factor, color in (
            (1.5, COLORS["neon_dim"]),
            (1.15, COLORS["neon_soft"]),
            (0.82, COLORS["neon"]),
        ):
            self.orb.create_oval(
                cx - core * factor,
                cy - core * factor,
                cx + core * factor,
                cy + core * factor,
                outline=color,
                width=1,
                tags="dynamic",
            )

        if thinking:
            state_text = "АНАЛИЗ"
        elif speaking:
            state_text = "ГОЛОС"
        elif self._state.get("listening"):
            state_text = "ОНЛАЙН"
        else:
            state_text = "ОЖИДАНИЕ"
        self.orb.create_text(
            cx,
            cy - 14,
            text="КАТЯ",
            fill=COLORS["text"],
            font=("Segoe UI", max(14, int(radius * 0.13)), "bold"),
            tags="dynamic",
        )
        self.orb.create_text(
            cx,
            cy + 18,
            text=f"CORE 2.11.0 // {state_text}",
            fill=COLORS["neon_soft"],
            font=("Consolas", max(7, int(radius * 0.06)), "bold"),
            tags="dynamic",
        )
        if level > 0.02:
            self.orb.create_text(
                cx,
                cy + 36,
                text=f"INPUT {level * 100:03.0f}%",
                fill=COLORS["neon_dim"],
                font=("Consolas", 8),
                tags="dynamic",
            )

    # ==================================================================
    # Shutdown
    # ==================================================================
    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.status_text.configure(text="Отключение протоколов и потоков…")
        self.withdraw()

        def worker() -> None:
            try:
                self.engine.shutdown()
            except Exception:
                logger.exception("Engine shutdown failed")
            finally:
                self._events.put(("__shutdown_done__", {}))

        threading.Thread(target=worker, name="KatyaShutdown", daemon=True).start()


def run_app() -> int:
    app = KatyaApp()
    try:
        app.mainloop()
    finally:
        try:
            app.engine.shutdown()
        except Exception:
            logger.exception("Final shutdown failed")
    return 0
