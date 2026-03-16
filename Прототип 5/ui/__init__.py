# ui/__init__.py - Главное окно приложения

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from collections import Counter
import threading
import time
import os
import sys
import ctypes
from ctypes import wintypes
from queue import Empty, Full

import config
from core import AudioPlayer, TTSEngine, TextTranslator
from storage import AudioCache, HistoryManager, SettingsManager
from threading_workers import (
    AudioPrepDispatcher,
    AudioPrepWorker,
    PlaybackWorker,
    Queues,
    TextComparisonWorker,
    ThreadLifecycle,
)
from utils.logger import log
from utils.subtitle_resource_importer import import_subtitle_resource
from utils.subtitle_source_scanner import SubtitleSourceScanner
from utils.ue_resource_extractor import DEFAULT_COMMAND_TEMPLATE, UEResourceExtractor

try:
    import psutil
except Exception:
    psutil = None


class MainWindow:
    """Компактный UI для import/extract + TTS pipeline."""

    _AUTO_DIRECT_IMPORT_EXTS = {".txt", ".log", ".json", ".jsonl", ".xml", ".srt", ".sub", ".csv", ".locres"}
    _AUTO_MANIFEST_EXTRACT_EXTS = {".txt", ".json", ".jsonl", ".xml", ".srt", ".sub", ".csv", ".locres"}
    _AUTO_BLOCKED_BINARY_EXTS = {".uasset", ".uexp"}

    def __init__(self):
        self.root = tk.Tk()
        self._configure_styles()
        self.root.title(config.WINDOW_TITLE)
        self.root.resizable(config.WINDOW_RESIZABLE, config.WINDOW_RESIZABLE)
        self.root.minsize(config.WINDOW_WIDTH, config.WINDOW_HEIGHT)

        self.lang_code_to_label = dict(getattr(config, "LANGUAGE_OPTIONS", []))
        self.lang_label_to_code = {v: k for k, v in self.lang_code_to_label.items()}
        self.voice_id_to_label = {}
        self.voice_label_to_id = {}

        self.settings = SettingsManager()

        self.game_root_var = tk.StringVar(
            value=str(self.settings.get("game_root", getattr(config, "GAME_ROOT", "")) or "").strip()
        )
        self.auto_detect_game_root_var = tk.BooleanVar(
            value=bool(
                self.settings.get(
                    "auto_detect_game_root",
                    getattr(config, "GAME_AUTODETECT_ENABLED", True),
                )
            )
        )
        self.detected_game_exe_var = tk.StringVar(value="Автоопределение: инициализация...")
        self._game_autodetect_after_id = None
        self._last_detected_exe_path = ""
        self.import_file_var = tk.StringVar(value="")
        self.scan_candidate_var = tk.StringVar(value="")
        saved_extractor_tool = str(
            self.settings.get("ue_extractor_tool", getattr(config, "UE_EXTRACTOR_TOOL", "")) or ""
        ).strip()
        if not saved_extractor_tool:
            saved_extractor_tool = str(getattr(config, "UE_EXTRACTOR_TOOL", "") or "").strip()
        self.extractor_tool_var = tk.StringVar(value=saved_extractor_tool)
        self.extractor_output_dir_var = tk.StringVar(
            value=str(
                self.settings.get(
                    "ue_extractor_output_dir",
                    getattr(config, "UE_EXTRACTOR_OUTPUT_DIR", os.path.join(config.CONFIG_DIR, "extracted_resources")),
                )
                or ""
            ).strip()
        )
        self.extractor_command_template_var = tk.StringVar(
            value=str(
                self.settings.get(
                    "ue_extractor_command_template",
                    getattr(config, "UE_EXTRACTOR_COMMAND_TEMPLATE", DEFAULT_COMMAND_TEMPLATE),
                )
                or DEFAULT_COMMAND_TEMPLATE
            ).strip()
        )
        self.extract_container_var = tk.StringVar(value="")
        self.scan_candidates = []
        self.scan_candidate_labels = []
        self.scan_candidate_map = {}
        self.extract_container_candidates = []
        self.extract_plan = None
        self.imported_subtitles = []
        self.imported_source = ""
        self.imported_source_type = ""
        self.subtitle_scanner = SubtitleSourceScanner(max_files=getattr(config, "SCAN_MAX_FILES", 25000))
        self.scan_thread = None
        self.scan_in_progress = False
        self.extract_thread = None
        self.extract_in_progress = False
        self._scan_request_mode = "manual"
        self._scan_request_root_norm = ""
        self._extract_request_mode = "manual"
        self._extract_request_root_norm = ""
        self._extract_request_candidate_key = ""
        self._auto_scan_on_game_detect = bool(getattr(config, "AUTO_SCAN_ON_GAME_DETECT", True))
        self._auto_import_best_candidate = bool(getattr(config, "AUTO_IMPORT_BEST_CANDIDATE", True))
        self._auto_last_scanned_root_norm = ""
        self._auto_scan_inflight_root_norm = ""
        self._auto_pending_game_root = ""
        self._auto_pending_game_root_norm = ""
        self._auto_last_imported_root_norm = ""
        self._auto_last_imported_candidate_key = ""

        self.read_lang_code = self.settings.get("read_language", getattr(config, "DEFAULT_READ_LANGUAGE", "auto"))
        self.speech_lang_code = self.settings.get("speech_language", getattr(config, "DEFAULT_SPEECH_LANGUAGE", "ru"))
        if self.read_lang_code not in self.lang_code_to_label:
            self.read_lang_code = "auto"
        if self.speech_lang_code not in self.lang_code_to_label:
            self.speech_lang_code = "ru"

        config.TRANSLATOR_SOURCE_LANG = self.read_lang_code
        config.TRANSLATOR_TARGET_LANG = self.speech_lang_code
        default_voice = getattr(config, "TTS_VOICE_BY_LANGUAGE", {}).get(self.speech_lang_code)
        saved_voice = self.settings.get("tts_voice", getattr(config, "TTS_VOICE", "ru-RU-DmitryNeural"))
        allowed_voices = [voice_id for voice_id, _ in getattr(config, "TTS_VOICE_OPTIONS", {}).get(self.speech_lang_code, [])]
        if saved_voice in allowed_voices:
            config.TTS_VOICE = saved_voice
        elif default_voice:
            config.TTS_VOICE = default_voice

        # Бизнес-компоненты
        self.tts_engine = TTSEngine()
        self.translator = TextTranslator()
        self.audio_player = AudioPlayer()
        try:
            startup_volume = int(self.settings.get("volume", config.AUDIO_VOLUME_DEFAULT))
            self.audio_player.set_volume(startup_volume)
        except Exception:
            pass
        self.audio_cache = AudioCache()
        self.history = HistoryManager()

        # Worker-ссылки
        self.text_comp_worker = None
        self.audio_prep_worker = None
        self.audio_prep_dispatcher = None
        self.playback_worker = None
        self.import_source_thread = None
        self.threads = []

        # Состояние UI
        self.is_running = False
        self.is_paused = False
        self.read_language_var = tk.StringVar(value=self.lang_code_to_label.get(self.read_lang_code, "Авто"))
        self.speech_language_var = tk.StringVar(value=self.lang_code_to_label.get(self.speech_lang_code, "Русский"))
        self.voice_var = tk.StringVar(value="")

        self._build_ui()
        self._refresh_voice_options(self.speech_lang_code, select_voice=config.TTS_VOICE)
        self._apply_initial_geometry()
        self._update_game_detect_status(exe_path="", game_root=None)
        self._schedule_game_autodetect_poll(initial=True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        log("✅ MainWindow инициализирована успешно", level="INFO")

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        # Цветовая палитра (Modern Dark / VS Code style)
        BG_COLOR = "#2d2d2d"      # Основной фон
        FG_COLOR = "#ffffff"      # Основной текст
        ACCENT = "#007acc"        # Акцентный синий
        ACCENT_HOVER = "#0098ff"  # Акцент при наведении
        SEC_BG = "#3e3e42"        # Фон полей ввода/списков
        DISABLED = "#555555"      # Цвет отключенных элементов
        BORDER = "#2d2d2d"        # Цвет границ (скрываем их под фон)
        
        # Общие настройки
        style.configure(".", background=BG_COLOR, foreground=FG_COLOR, font=("Segoe UI", 10))
        
        # Frames
        style.configure("TFrame", background=BG_COLOR)
        
        # LabelFrame
        style.configure("TLabelFrame", 
            background=BG_COLOR, 
            foreground=FG_COLOR,
            relief="flat", 
            borderwidth=1
        )
        style.configure("TLabelFrame.Label", 
            background=BG_COLOR, 
            foreground=ACCENT, 
            font=("Segoe UI", 10, "bold")
        )
        
        # Buttons
        style.configure("TButton", 
            background=SEC_BG, 
            foreground=FG_COLOR, 
            borderwidth=0, 
            focuscolor=BG_COLOR,
            padding=(6, 3)
        )
        style.map("TButton",
            background=[("active", "#4e4e52"), ("disabled", "#252526")],
            foreground=[("disabled", "#888888")]
        )
        
        # Accent Button (Start)
        style.configure("Accent.TButton", 
            background=ACCENT, 
            foreground="white"
        )
        style.map("Accent.TButton",
            background=[("active", ACCENT_HOVER), ("disabled", "#252526")]
        )
        
        # Combobox
        style.configure("TCombobox", 
            fieldbackground=SEC_BG, 
            background=SEC_BG, 
            foreground=FG_COLOR, 
            arrowcolor=FG_COLOR,
            borderwidth=0,
            selectbackground=ACCENT,
            selectforeground="white"
        )
        style.map("TCombobox",
            fieldbackground=[("readonly", SEC_BG)],
            selectbackground=[("readonly", ACCENT)],
            selectforeground=[("readonly", "white")]
        )

        # Entry
        style.configure(
            "TEntry",
            fieldbackground=SEC_BG,
            background=SEC_BG,
            foreground=FG_COLOR,
            borderwidth=0,
            insertcolor=FG_COLOR,
            padding=(6, 4),
        )
        style.map(
            "TEntry",
            fieldbackground=[("disabled", "#252526"), ("!disabled", SEC_BG)],
            foreground=[("disabled", "#888888"), ("!disabled", FG_COLOR)],
        )
        
        # Labels
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), foreground=FG_COLOR)
        style.configure("Status.TLabel", font=("Segoe UI", 9))
        style.configure("Error.TLabel", foreground="#ff6b6b")

        # Настройка цветов корневого окна
        self.root.configure(bg=BG_COLOR)

    def _build_ui(self):
        # Настройка сетки: контент тянется
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        container = ttk.Frame(self.root, padding=10)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)

        # Заголовок
        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(header, text=config.APP_NAME, style="Header.TLabel").pack(side="left")

        # --- Блок Управления ---
        controls = ttk.LabelFrame(container, text="Управление", padding=(9, 6))
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 7))
        controls.columnconfigure((0, 1, 2), weight=1)

        self.btn_start = ttk.Button(controls, text="▶ Начать", command=self.on_start_work, style="Accent.TButton")
        self.btn_stop = ttk.Button(controls, text="■ Стоп", command=self.on_stop_work, state=tk.DISABLED)
        self.btn_pause = ttk.Button(controls, text="⏸ Пауза", command=self.on_pause, state=tk.DISABLED)

        self.btn_start.grid(row=0, column=0, padx=4, sticky="ew")
        self.btn_stop.grid(row=0, column=1, padx=4, sticky="ew")
        self.btn_pause.grid(row=0, column=2, padx=4, sticky="ew")

        # --- Языки и Голос ---
        lang_box = ttk.LabelFrame(container, text="Языки и Озвучка", padding=(9, 6))
        lang_box.grid(row=4, column=0, sticky="ew", pady=(0, 7))
        lang_box.columnconfigure(1, weight=1)

        # Чтение
        ttk.Label(lang_box, text="Чтение:").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.combo_read_language = ttk.Combobox(
            lang_box, 
            textvariable=self.read_language_var, 
            values=tuple(self.lang_code_to_label.values()), 
            state="readonly"
        )
        self.combo_read_language.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=(0, 6))
        
        # Общая кнопка применить для языков
        ttk.Button(lang_box, text="Применить", command=self.on_apply_languages, width=10).grid(
            row=0, column=2, rowspan=2, padx=(8, 0), sticky="ns"
        )

        # Озвучка
        ttk.Label(lang_box, text="Озвучка:").grid(row=1, column=0, sticky="w")
        speech_values = tuple(label for code, label in getattr(config, "LANGUAGE_OPTIONS", []) if code != "auto")
        self.combo_speech_language = ttk.Combobox(
            lang_box, 
            textvariable=self.speech_language_var, 
            values=speech_values, 
            state="readonly"
        )
        self.combo_speech_language.grid(row=1, column=1, sticky="ew", padx=(8, 0))

        # Голос (отдельная строка)
        ttk.Label(lang_box, text="Голос:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.combo_voice = ttk.Combobox(
            lang_box,
            textvariable=self.voice_var,
            values=(),
            state="readonly"
        )
        self.combo_voice.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        
        ttk.Button(lang_box, text="Обновить", command=self.on_apply_voice, width=10).grid(
            row=2, column=2, padx=(8, 0), pady=(8, 0), sticky="e"
        )

        # --- Инструменты ---
        tools_frame = ttk.Frame(container)
        tools_frame.grid(row=5, column=0, sticky="ew", pady=(0, 7))
        
        ttk.Button(tools_frame, text="Очистить кеш", command=self.on_clear_cache).pack(side="left", padx=(0, 8))
        ttk.Button(tools_frame, text="Логи", command=self.on_show_logs).pack(side="left")

        # --- Статус бар ---
        status_box = ttk.LabelFrame(container, text="Статус", padding=(8, 4))
        status_box.grid(row=6, column=0, sticky="ew")
        status_box.columnconfigure(0, weight=1)
        
        self.status_label = ttk.Label(status_box, text="🟢 Готово", foreground="#6ec273", font=("Segoe UI", 10, "bold"))
        self.status_label.grid(row=0, column=0, sticky="w")

        # --- Поиск источников субтитров ---
        scan_box = ttk.LabelFrame(container, text="Сканер источников", padding=(9, 6))
        scan_box.grid(row=2, column=0, sticky="nsew", pady=(0, 6))
        scan_box.columnconfigure(1, weight=1)
        scan_box.rowconfigure(1, weight=1)

        ttk.Label(scan_box, text="Папка игры:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        self.entry_game_root = ttk.Entry(scan_box, textvariable=self.game_root_var)
        self.entry_game_root.grid(row=0, column=1, sticky="ew", pady=(0, 4))
        self.btn_browse_game_root = ttk.Button(scan_box, text="Обзор игры", command=self.on_browse_game_root, width=10)
        self.btn_browse_game_root.grid(row=0, column=2, sticky="e", padx=(6, 0), pady=(0, 4))
        self.btn_scan_sources = ttk.Button(scan_box, text="Сканировать", command=self.on_scan_sources, width=10)
        self.btn_scan_sources.grid(row=0, column=3, sticky="e", padx=(6, 0), pady=(0, 4))

        scan_results_wrap = ttk.Frame(scan_box)
        scan_results_wrap.grid(row=1, column=0, columnspan=4, sticky="nsew")
        scan_results_wrap.columnconfigure(0, weight=1)
        scan_results_wrap.rowconfigure(0, weight=1)

        self.scan_results_text = tk.Text(scan_results_wrap, height=4, wrap=tk.WORD)
        self.scan_results_text.grid(row=0, column=0, sticky="nsew")
        scan_scroll = ttk.Scrollbar(scan_results_wrap, orient="vertical", command=self.scan_results_text.yview)
        scan_scroll.grid(row=0, column=1, sticky="ns")
        self.scan_results_text.configure(yscrollcommand=scan_scroll.set, state=tk.DISABLED)

        self.btn_copy_scan_results = ttk.Button(
            scan_results_wrap,
            text="Копировать",
            command=self.on_copy_scan_results,
            width=10,
        )
        self.btn_copy_scan_results.grid(row=1, column=0, sticky="e", pady=(4, 0))

        ttk.Label(scan_box, text="Кандидат из scan:").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 4))
        self.combo_scan_candidate = ttk.Combobox(
            scan_box,
            textvariable=self.scan_candidate_var,
            values=(),
            state="readonly",
        )
        self.combo_scan_candidate.grid(row=2, column=1, columnspan=3, sticky="ew", pady=(6, 4))

        ttk.Label(scan_box, text="Локальный файл:").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        self.entry_import_file = ttk.Entry(scan_box, textvariable=self.import_file_var)
        self.entry_import_file.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(0, 4))
        self.btn_browse_import_file = ttk.Button(
            scan_box,
            text="Обзор",
            command=self.on_browse_import_file,
            width=10,
        )
        self.btn_browse_import_file.grid(row=3, column=3, sticky="e", padx=(6, 0), pady=(0, 4))

        ttk.Label(scan_box, text="Extractor tool:").grid(row=4, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        self.entry_extractor_tool = ttk.Entry(scan_box, textvariable=self.extractor_tool_var)
        self.entry_extractor_tool.grid(row=4, column=1, columnspan=2, sticky="ew", pady=(0, 4))
        self.btn_browse_extractor_tool = ttk.Button(
            scan_box,
            text="Обзор tool",
            command=self.on_browse_extractor_tool,
            width=10,
        )
        self.btn_browse_extractor_tool.grid(row=4, column=3, sticky="e", padx=(6, 0), pady=(0, 4))

        ttk.Label(scan_box, text="Output dir:").grid(row=5, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        self.entry_extractor_output = ttk.Entry(scan_box, textvariable=self.extractor_output_dir_var)
        self.entry_extractor_output.grid(row=5, column=1, columnspan=2, sticky="ew", pady=(0, 4))
        self.btn_browse_extractor_output = ttk.Button(
            scan_box,
            text="Обзор output",
            command=self.on_browse_extractor_output,
            width=10,
        )
        self.btn_browse_extractor_output.grid(row=5, column=3, sticky="e", padx=(6, 0), pady=(0, 4))

        ttk.Label(scan_box, text="Extract command:").grid(row=6, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        self.entry_extractor_template = ttk.Entry(scan_box, textvariable=self.extractor_command_template_var)
        self.entry_extractor_template.grid(row=6, column=1, columnspan=3, sticky="ew", pady=(0, 4))

        ttk.Label(scan_box, text="Container candidate:").grid(row=7, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        self.combo_extract_container = ttk.Combobox(
            scan_box,
            textvariable=self.extract_container_var,
            values=(),
            state="readonly",
        )
        self.combo_extract_container.grid(row=7, column=1, sticky="ew", pady=(0, 4))

        self.btn_prepare_extract = ttk.Button(
            scan_box,
            text="Подготовить extract",
            command=self.on_prepare_extract,
            width=15,
        )
        self.btn_prepare_extract.grid(row=7, column=2, sticky="e", padx=(6, 0), pady=(0, 4))

        self.btn_run_extract = ttk.Button(
            scan_box,
            text="Запустить extract",
            command=self.on_run_extract,
            width=14,
        )
        self.btn_run_extract.grid(row=7, column=3, sticky="e", padx=(6, 0), pady=(0, 4))

        self.btn_import_resource = ttk.Button(
            scan_box,
            text="Импортировать",
            command=self.on_import_subtitle_resource,
            width=12,
        )
        self.btn_import_resource.grid(row=8, column=3, sticky="e", padx=(6, 0), pady=(0, 4))

        ttk.Label(scan_box, text="Preview импортированных строк:").grid(
            row=8,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(0, 4),
        )

        import_preview_wrap = ttk.Frame(scan_box)
        import_preview_wrap.grid(row=9, column=0, columnspan=4, sticky="nsew")
        import_preview_wrap.columnconfigure(0, weight=1)
        import_preview_wrap.rowconfigure(0, weight=1)

        self.import_preview_text = tk.Text(import_preview_wrap, height=3, wrap=tk.WORD)
        self.import_preview_text.grid(row=0, column=0, sticky="nsew")
        import_preview_scroll = ttk.Scrollbar(import_preview_wrap, orient="vertical", command=self.import_preview_text.yview)
        import_preview_scroll.grid(row=0, column=1, sticky="ns")
        self.import_preview_text.configure(yscrollcommand=import_preview_scroll.set, state=tk.DISABLED)

        self.chk_auto_game_root = ttk.Checkbutton(
            scan_box,
            text="Автоопределение игры (foreground)",
            variable=self.auto_detect_game_root_var,
            command=self.on_toggle_auto_game_root,
        )
        self.chk_auto_game_root.grid(row=10, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.label_detected_game_exe = ttk.Label(
            scan_box,
            textvariable=self.detected_game_exe_var,
            style="Status.TLabel",
            wraplength=430,
        )
        self.label_detected_game_exe.grid(row=10, column=2, columnspan=2, sticky="e", pady=(6, 0))

        self._set_scan_output("Укажите папку игры и нажмите 'Сканировать'.")
        self._set_import_preview("Импорт не выполнен.")

    def on_toggle_auto_game_root(self):
        enabled = bool(self.auto_detect_game_root_var.get())
        self.settings.set("auto_detect_game_root", enabled)
        if enabled:
            self._update_game_detect_status(exe_path="", game_root=(self.game_root_var.get() or "").strip())
            self._schedule_game_autodetect_poll(initial=True)
        else:
            self._update_game_detect_status(exe_path="", game_root=(self.game_root_var.get() or "").strip())

    def _schedule_game_autodetect_poll(self, initial: bool = False):
        if self._game_autodetect_after_id:
            try:
                self.root.after_cancel(self._game_autodetect_after_id)
            except Exception:
                pass
            self._game_autodetect_after_id = None

        interval_ms = int(getattr(config, "GAME_AUTODETECT_POLL_INTERVAL_MS", 1500))
        interval_ms = max(500, interval_ms)
        delay = 100 if initial else interval_ms
        self._game_autodetect_after_id = self.root.after(delay, self._game_autodetect_poll)

    def _game_autodetect_poll(self):
        try:
            if not sys.platform.startswith("win"):
                self._update_game_detect_status(exe_path="", game_root=(self.game_root_var.get() or "").strip())
                return

            if not bool(self.auto_detect_game_root_var.get()):
                self._update_game_detect_status(exe_path="", game_root=(self.game_root_var.get() or "").strip())
                return

            exe_path = self._get_foreground_process_path_windows()
            if not exe_path:
                self._update_game_detect_status(exe_path="", game_root=(self.game_root_var.get() or "").strip())
                return

            guessed_root = self._guess_game_root_from_exe(exe_path)
            current_root = (self.game_root_var.get() or "").strip()
            if guessed_root and os.path.isdir(guessed_root):
                if self._normalized_path(current_root) != self._normalized_path(guessed_root):
                    self.game_root_var.set(guessed_root)
                    self.settings.set("game_root", guessed_root)
                    log(f"🎮 Автоопределение игры: {guessed_root}", level="INFO")
                    self._on_new_detected_game_root(guessed_root)
                self._update_game_detect_status(exe_path=exe_path, game_root=guessed_root)
            else:
                self._update_game_detect_status(exe_path=exe_path, game_root=current_root)
        except Exception as e:
            log(f"⚠️ Ошибка автоопределения игры: {e}", level="DEBUG")
        finally:
            self._schedule_game_autodetect_poll(initial=False)

    def _normalized_path(self, path: str) -> str:
        if not path:
            return ""
        return os.path.normcase(os.path.normpath(path))

    def _get_foreground_process_path_windows(self) -> str:
        if not sys.platform.startswith("win"):
            return ""

        pid = self._get_foreground_pid_windows()
        if not pid or pid == os.getpid():
            return ""

        exe_path = ""
        if psutil is not None:
            try:
                exe_path = str(psutil.Process(pid).exe() or "").strip()
            except Exception:
                exe_path = ""

        if not exe_path:
            exe_path = self._query_full_process_image_name(pid)

        if not exe_path:
            return ""

        exe_name = os.path.basename(exe_path).lower()
        excluded = set(getattr(config, "GAME_AUTODETECT_EXCLUDED_EXE_NAMES", set()) or set())
        if exe_name in excluded:
            return ""

        return exe_path

    def _get_foreground_pid_windows(self) -> int:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return 0

        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value or 0)

    def _query_full_process_image_name(self, pid: int) -> str:
        if not pid:
            return ""

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32

        process_handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not process_handle:
            return ""

        try:
            buffer_len = 32768
            image_path = ctypes.create_unicode_buffer(buffer_len)
            size = wintypes.DWORD(buffer_len)
            ok = kernel32.QueryFullProcessImageNameW(process_handle, 0, image_path, ctypes.byref(size))
            if not ok:
                return ""
            return str(image_path.value or "").strip()
        finally:
            kernel32.CloseHandle(process_handle)

    def _guess_game_root_from_exe(self, exe_path: str) -> str:
        if not exe_path:
            return ""

        exe_dir = os.path.dirname(os.path.abspath(exe_path))
        if not os.path.isdir(exe_dir):
            return ""

        parts = exe_dir.split(os.sep)
        parts_lower = [p.lower() for p in parts]
        if "binaries" in parts_lower:
            idx = len(parts_lower) - 1 - parts_lower[::-1].index("binaries")
            ue_root = os.sep.join(parts[:idx])
            if ue_root and os.path.isdir(ue_root):
                return ue_root

        best_path = ""
        best_score = float("-inf")
        cursor = exe_dir

        for depth in range(0, 7):
            if not cursor or not os.path.isdir(cursor):
                break

            score = self._score_game_root_candidate(cursor) - (depth * 0.1)
            if score > best_score:
                best_score = score
                best_path = cursor

            parent = os.path.dirname(cursor)
            if parent == cursor:
                break
            cursor = parent

        if best_score < 1.0:
            return ""

        return best_path

    def _score_game_root_candidate(self, path: str) -> float:
        score = 0.0
        try:
            entries = set(os.listdir(path))
        except Exception:
            return score

        lower_entries = {item.lower() for item in entries}
        if "binaries" in lower_entries:
            score += 4.0
        if "content" in lower_entries:
            score += 4.0
            if os.path.isdir(os.path.join(path, "Content", "Paks")):
                score += 4.0
        if "engine" in lower_entries:
            score += 2.5

        try:
            if any(item.lower().endswith(".uproject") for item in entries):
                score += 2.0
        except Exception:
            pass

        return score

    def _update_game_detect_status(self, exe_path: str, game_root: str | None):
        if not hasattr(self, "detected_game_exe_var"):
            return

        enabled = bool(self.auto_detect_game_root_var.get())
        state = "вкл" if enabled else "выкл"
        root_view = (game_root or "").strip() or "-"

        if not sys.platform.startswith("win"):
            self.detected_game_exe_var.set("Автоопределение: только для Windows")
            return

        exe_trimmed = (exe_path or "").strip()
        if exe_trimmed:
            if self._last_detected_exe_path != exe_trimmed:
                self._last_detected_exe_path = exe_trimmed
                log(f"🪟 Active process: {exe_trimmed}", level="DEBUG")
            self.detected_game_exe_var.set(
                f"Автоопределение [{state}] | exe: {os.path.basename(exe_trimmed)} | root: {root_view}"
            )
        else:
            self.detected_game_exe_var.set(f"Автоопределение [{state}] | exe: - | root: {root_view}")

    def _apply_initial_geometry(self):
        self.root.update_idletasks()

        req_width = self.root.winfo_reqwidth()
        req_height = self.root.winfo_reqheight()
        width = max(config.WINDOW_WIDTH, req_width + 12)
        height = max(config.WINDOW_HEIGHT, req_height + 12)

        self.root.minsize(width, height)
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _update_ui_running(self):
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_pause.config(state=tk.NORMAL)

    def _update_ui_stopped(self):
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_pause.config(state=tk.DISABLED, text="⏸ Пауза")

    def on_browse_game_root(self):
        selected = filedialog.askdirectory(title="Выберите папку установленной игры")
        if selected:
            self.game_root_var.set(selected)
            self.settings.set("game_root", selected)

    def _on_new_detected_game_root(self, game_root: str):
        if not self._auto_scan_on_game_detect:
            return
        if not bool(self.auto_detect_game_root_var.get()):
            return
        self._try_auto_scan_for_root(game_root, source="foreground-detect")

    def _try_auto_scan_for_root(self, game_root: str, source: str = "auto"):
        root = (game_root or "").strip()
        root_norm = self._normalized_path(root)
        if not root or not root_norm or not os.path.isdir(root):
            return

        if root_norm == self._auto_last_scanned_root_norm or root_norm == self._auto_scan_inflight_root_norm:
            return

        if self.scan_in_progress or self.extract_in_progress:
            self._auto_pending_game_root = root
            self._auto_pending_game_root_norm = root_norm
            log(
                f"⏳ Автопайплайн отложен ({source}): scan/extract уже выполняется для {root}",
                level="DEBUG",
            )
            return

        started = self._start_scan_sources(root, request_mode="auto", request_root_norm=root_norm)
        if started:
            self._auto_last_scanned_root_norm = root_norm
            self._auto_scan_inflight_root_norm = root_norm
            self.status_label.config(text="🔎 Автосканирование источников", foreground="orange")
            log(f"🤖 Автосканирование запущено ({source}): {root}", level="INFO")

    def _run_pending_auto_scan_if_idle(self):
        if not self._auto_pending_game_root_norm:
            return
        if self.scan_in_progress or self.extract_in_progress:
            return

        pending_root = self._auto_pending_game_root
        pending_norm = self._auto_pending_game_root_norm
        self._auto_pending_game_root = ""
        self._auto_pending_game_root_norm = ""

        if pending_norm and pending_norm not in {
            self._auto_last_scanned_root_norm,
            self._auto_scan_inflight_root_norm,
        }:
            self._try_auto_scan_for_root(pending_root, source="pending")

    def _start_scan_sources(self, game_root: str, request_mode: str, request_root_norm: str = "") -> bool:
        root = (game_root or "").strip()
        if not root or not os.path.isdir(root):
            return False
        if self.scan_in_progress:
            return False

        self.settings.set("game_root", root)
        self.scan_in_progress = True
        self._scan_request_mode = request_mode
        self._scan_request_root_norm = request_root_norm or self._normalized_path(root)
        self.btn_scan_sources.config(state=tk.DISABLED)
        self._set_scan_output("Сканирование запущено. Это может занять некоторое время...")
        self.status_label.config(text="🔎 Идёт сканирование источников", foreground="orange")

        self.scan_thread = threading.Thread(
            target=self._scan_sources_worker,
            args=(root, request_mode),
            daemon=True,
            name="SubtitleSourceScanner",
        )
        self.scan_thread.start()
        return True

    def _classify_auto_candidate(self, candidate_path: str) -> tuple[str, str, str]:
        raw_path = str(candidate_path or "").strip()
        if not raw_path:
            return "ignore", "", ""

        parse_ok, _, internal_path, _ = UEResourceExtractor.parse_manifest_style(raw_path)
        if parse_ok:
            internal_ext = os.path.splitext(internal_path)[1].lower()
            if internal_ext in self._AUTO_MANIFEST_EXTRACT_EXTS:
                return "manifest-extract", internal_ext, internal_path
            if internal_ext in self._AUTO_BLOCKED_BINARY_EXTS:
                return "ignore", internal_ext, internal_path
            return "ignore", internal_ext, internal_path

        local_abs = os.path.abspath(os.path.expanduser(raw_path))
        ext = os.path.splitext(local_abs)[1].lower()
        if ext in self._AUTO_BLOCKED_BINARY_EXTS:
            return "ignore", ext, ""
        if ext in self._AUTO_DIRECT_IMPORT_EXTS and os.path.isfile(local_abs):
            return "direct-import", ext, ""
        return "ignore", ext, ""

    def _pick_best_auto_candidate(self, candidates: list[dict]) -> tuple[dict | None, str, str]:
        ranked: list[tuple[int, int, dict, str, str]] = []

        for item in candidates or []:
            path = str(item.get("path", "") or "").strip()
            if not path:
                continue
            mode, ext, _ = self._classify_auto_candidate(path)
            if mode == "direct-import":
                priority = 0
            elif mode == "manifest-extract":
                priority = 1
            else:
                continue
            score = int(item.get("score", 0) or 0)
            ranked.append((priority, -score, item, mode, ext))

        if not ranked:
            return None, "", ""

        ranked.sort(key=lambda row: (row[0], row[1]))
        _, _, best_item, best_mode, best_ext = ranked[0]
        return best_item, best_mode, best_ext

    def _describe_auto_skip_reasons(self, candidates: list[dict]) -> str:
        counters: Counter[str] = Counter()
        samples: list[str] = []

        for item in candidates or []:
            path = str(item.get("path", "") or "").strip()
            if not path:
                continue

            mode, ext, internal_path = self._classify_auto_candidate(path)
            if mode != "ignore":
                continue

            display_ext = ext or os.path.splitext(path)[1].lower() or "<no-ext>"
            kind = str(item.get("kind", "unknown") or "unknown")
            origin = "manifest" if "::" in path else "local"
            counters[f"{origin} {display_ext} / {kind}"] += 1

            if len(samples) < 5:
                samples.append(internal_path or path)

        if not counters:
            return ""

        top_reasons = ", ".join(f"{name}: {count}" for name, count in counters.most_common(4))
        lines = [
            "Автоимпорт не нашёл подходящий ресурс среди результатов сканирования.",
            f"Чаще всего были пропущены: {top_reasons}",
        ]
        if samples:
            lines.append("Примеры пропущенных путей:")
            lines.extend(f"- {sample}" for sample in samples)
        return "\n".join(lines)

    def _make_auto_candidate_key(self, candidate_path: str) -> str:
        raw_path = str(candidate_path or "").strip()
        parse_ok, manifest_path, internal_path, _ = UEResourceExtractor.parse_manifest_style(raw_path)
        if parse_ok:
            return f"manifest::{self._normalized_path(manifest_path)}::{internal_path.lower()}"
        return self._normalized_path(os.path.abspath(os.path.expanduser(raw_path)))

    def _run_auto_best_candidate_pipeline(self, candidates: list[dict], root_norm: str):
        if not self._auto_import_best_candidate:
            return

        current_norm = self._normalized_path((self.game_root_var.get() or "").strip())
        if root_norm and current_norm and root_norm != current_norm:
            log("ℹ️ Автоимпорт пропущен: активная игра изменилась после сканирования", level="INFO")
            self.status_label.config(text="ℹ️ Автоскан завершён, но активная игра уже другая", foreground="orange")
            return

        best_item, mode, ext = self._pick_best_auto_candidate(candidates)
        if not best_item:
            self.status_label.config(text="ℹ️ Авто: нет подходящих кандидатов для импорта", foreground="orange")
            skip_details = self._describe_auto_skip_reasons(candidates)
            if skip_details:
                self._set_import_preview(skip_details)
                log(f"ℹ️ Автоимпорт: подходящие кандидаты не найдены. {skip_details.splitlines()[1]}", level="INFO")
            log("ℹ️ Автоимпорт: подходящие кандидаты не найдены", level="INFO")
            return

        candidate_path = str(best_item.get("path", "") or "").strip()
        candidate_key = self._make_auto_candidate_key(candidate_path)
        if (
            candidate_key
            and self._auto_last_imported_root_norm == root_norm
            and self._auto_last_imported_candidate_key == candidate_key
        ):
            log("ℹ️ Автоимпорт пропущен: лучший кандидат уже импортировался ранее", level="DEBUG")
            return

        if mode == "direct-import":
            local_target = os.path.abspath(os.path.expanduser(candidate_path))
            self.import_file_var.set(local_target)
            imported = self._import_subtitle_resource_target(local_target, auto_mode=True)
            if imported:
                self._auto_last_imported_root_norm = root_norm
                self._auto_last_imported_candidate_key = candidate_key
                log(f"🤖 Автоимпорт выполнен: {local_target}", level="INFO")
            return

        if mode == "manifest-extract":
            started = self._try_auto_extract_candidate(
                candidate_path=candidate_path,
                root_norm=root_norm,
                candidate_key=candidate_key,
                internal_ext=ext,
            )
            if started:
                log(f"🤖 Авто-extract запущен для кандидата: {candidate_path}", level="INFO")

    def _try_auto_extract_candidate(
        self,
        candidate_path: str,
        root_norm: str,
        candidate_key: str,
        internal_ext: str,
    ) -> bool:
        if self.extract_in_progress or self.scan_in_progress:
            self.status_label.config(text="ℹ️ Авто-extract отложен: scan/extract уже выполняется", foreground="orange")
            return False

        game_root = (self.game_root_var.get() or "").strip()
        if not game_root or self._normalized_path(game_root) != root_norm or not os.path.isdir(game_root):
            log("ℹ️ Авто-extract отменён: game_root изменился", level="INFO")
            return False

        tool_path = (self.extractor_tool_var.get() or "").strip() or str(getattr(config, "UE_EXTRACTOR_TOOL", "") or "").strip()
        if not tool_path or not os.path.isfile(os.path.abspath(os.path.expanduser(tool_path))):
            self.status_label.config(text="ℹ️ Авто-extract пропущен: не найден extractor tool", foreground="orange")
            self._set_import_preview(
                "Авто-extract пропущен: не найден extractor tool.\n"
                f"Кандидат: {candidate_path}\n"
                f"Ожидаемый тип internal ресурса: {internal_ext or 'unknown'}"
            )
            log("⚠️ Авто-extract пропущен: extractor tool не найден", level="WARNING")
            return False

        output_dir = (self.extractor_output_dir_var.get() or "").strip()
        if not output_dir:
            output_dir = getattr(config, "UE_EXTRACTOR_OUTPUT_DIR", os.path.join(config.CONFIG_DIR, "extracted_resources"))
            self.extractor_output_dir_var.set(output_dir)

        template = (self.extractor_command_template_var.get() or "").strip() or DEFAULT_COMMAND_TEMPLATE
        self.extractor_command_template_var.set(template)
        self.extractor_tool_var.set(tool_path)

        plan = UEResourceExtractor.prepare_plan(
            raw_target=candidate_path,
            game_root=game_root,
            output_dir=output_dir,
            tool_path=tool_path,
            command_template=template,
        )

        if not plan.success:
            self.status_label.config(text="ℹ️ Авто-extract пропущен: не удалось подготовить plan", foreground="orange")
            self._set_import_preview(f"Авто-extract: prepare_plan ошибка\n{plan.message or plan.error}")
            log(f"⚠️ Авто-extract prepare_plan error: {plan.message or plan.error}", level="WARNING")
            return False

        if not plan.container_candidates:
            self.status_label.config(text="ℹ️ Авто-extract пропущен: контейнеры не найдены", foreground="orange")
            self._set_import_preview(
                "Авто-extract не выполнен: контейнеры .pak/.utoc/.ucas не найдены.\n"
                f"Кандидат: {candidate_path}\n"
                f"{plan.message}"
            )
            log("⚠️ Авто-extract пропущен: контейнеры не найдены", level="WARNING")
            return False

        selected_container = plan.selected_container or plan.container_candidates[0]
        if not selected_container:
            self.status_label.config(text="ℹ️ Авто-extract пропущен: container не выбран", foreground="orange")
            return False

        self.extract_plan = plan
        self._set_extract_candidates(plan.container_candidates)
        self.extract_container_var.set(selected_container)
        self._persist_extractor_settings()

        return self._start_extract_execution(
            tool_path=tool_path,
            container=selected_container,
            template=template,
            request_mode="auto",
            request_root_norm=root_norm,
            request_candidate_key=candidate_key,
        )

    def _start_extract_execution(
        self,
        tool_path: str,
        container: str,
        template: str,
        request_mode: str,
        request_root_norm: str = "",
        request_candidate_key: str = "",
    ) -> bool:
        if self.extract_in_progress:
            return False
        if not self.extract_plan or not getattr(self.extract_plan, "success", False):
            return False

        output_dir = (self.extractor_output_dir_var.get() or "").strip()
        if not output_dir:
            output_dir = getattr(config, "UE_EXTRACTOR_OUTPUT_DIR", os.path.join(config.CONFIG_DIR, "extracted_resources"))
            self.extractor_output_dir_var.set(output_dir)

        self.extract_plan.output_dir = os.path.abspath(os.path.expanduser(output_dir))
        self.extract_plan.expected_output_path = UEResourceExtractor.build_expected_output_path(
            self.extract_plan.output_dir,
            self.extract_plan.internal_path,
        )
        self.extract_plan.selected_container = container
        self.extract_plan.command_template = template
        self.extract_plan.command_preview = UEResourceExtractor.build_command_preview(
            tool=(tool_path or "<tool>"),
            container=(container or "<container>"),
            output_dir=(self.extract_plan.output_dir or "<output_dir>"),
            internal_path=self.extract_plan.internal_path,
            game_root=(self.extract_plan.game_root or "<game_root>"),
            expected_output_path=(self.extract_plan.expected_output_path or "<expected_output_path>"),
            command_template=template,
        )

        self.extract_in_progress = True
        self._extract_request_mode = request_mode
        self._extract_request_root_norm = request_root_norm
        self._extract_request_candidate_key = request_candidate_key
        self.btn_run_extract.config(state=tk.DISABLED)
        self.btn_prepare_extract.config(state=tk.DISABLED)
        self.status_label.config(
            text="⏳ Выполняется auto-extract" if request_mode == "auto" else "⏳ Выполняется external extract",
            foreground="orange",
        )

        self.extract_thread = threading.Thread(
            target=self._run_extract_worker,
            args=(tool_path, container, template),
            daemon=True,
            name="UEResourceExtractor",
        )
        self.extract_thread.start()
        return True

    def on_browse_import_file(self):
        selected = filedialog.askopenfilename(
            title="Выберите файл для импорта субтитров",
            filetypes=[
                ("Subtitle/Text", "*.txt *.log *.jsonl *.csv *.locres"),
                ("All files", "*.*"),
            ],
        )
        if selected:
            self.import_file_var.set(selected)

    def on_browse_extractor_tool(self):
        selected = filedialog.askopenfilename(
            title="Выберите extractor tool",
            filetypes=[
                ("Executable", "*.exe"),
                ("All files", "*.*"),
            ],
        )
        if selected:
            self.extractor_tool_var.set(selected)
            self.settings.set("ue_extractor_tool", selected)

    def on_browse_extractor_output(self):
        selected = filedialog.askdirectory(title="Выберите папку для extracted resources")
        if selected:
            self.extractor_output_dir_var.set(selected)
            self.settings.set("ue_extractor_output_dir", selected)

    def _selected_scan_candidate_path(self) -> str:
        selected_label = (self.scan_candidate_var.get() or "").strip()
        if not selected_label:
            return ""
        return (self.scan_candidate_map.get(selected_label, "") or "").strip()

    def _persist_extractor_settings(self):
        tool = (self.extractor_tool_var.get() or "").strip()
        output_dir = (self.extractor_output_dir_var.get() or "").strip()
        template = (self.extractor_command_template_var.get() or "").strip() or DEFAULT_COMMAND_TEMPLATE

        self.settings.set("ue_extractor_tool", tool)
        self.settings.set("ue_extractor_output_dir", output_dir)
        self.settings.set("ue_extractor_command_template", template)

    def _set_extract_candidates(self, candidates: list[str]):
        self.extract_container_candidates = list(candidates or [])
        self.combo_extract_container["values"] = tuple(self.extract_container_candidates)
        if self.extract_container_candidates:
            self.extract_container_var.set(self.extract_container_candidates[0])
        else:
            self.extract_container_var.set("")

    def on_prepare_extract(self):
        scan_target = self._selected_scan_candidate_path()
        if not scan_target:
            messagebox.showwarning("Extract", "Сначала выберите кандидата из scan результата.")
            return

        parse_ok, _, _, parse_error = UEResourceExtractor.parse_manifest_style(scan_target)
        if not parse_ok:
            self.extract_plan = None
            self._set_extract_candidates([])
            self._set_import_preview(
                "Extraction нужен только для manifest-style target (Manifest_*.txt :: internal/path).\n"
                f"Текущий target: {scan_target}\n"
                f"Причина: {parse_error}"
            )
            self.status_label.config(text="ℹ️ Extract не требуется для этого кандидата", foreground="orange")
            return

        game_root = (self.game_root_var.get() or "").strip()
        if not game_root or not os.path.isdir(game_root):
            messagebox.showwarning("Extract", "Укажите корректную папку игры для поиска контейнеров.")
            return

        output_dir = (self.extractor_output_dir_var.get() or "").strip()
        if not output_dir:
            output_dir = getattr(config, "UE_EXTRACTOR_OUTPUT_DIR", os.path.join(config.CONFIG_DIR, "extracted_resources"))
            self.extractor_output_dir_var.set(output_dir)

        template = (self.extractor_command_template_var.get() or "").strip() or DEFAULT_COMMAND_TEMPLATE
        self.extractor_command_template_var.set(template)
        self._persist_extractor_settings()

        plan = UEResourceExtractor.prepare_plan(
            raw_target=scan_target,
            game_root=game_root,
            output_dir=output_dir,
            tool_path=(self.extractor_tool_var.get() or "").strip(),
            command_template=template,
        )
        self.extract_plan = plan
        self._set_extract_candidates(plan.container_candidates)
        if plan.selected_container:
            self.extract_container_var.set(plan.selected_container)

        lines = [
            "Extraction plan:",
            f"manifest: {plan.manifest_path}",
            f"internal path: {plan.internal_path}",
            f"expected output: {plan.expected_output_path}",
            f"containers found: {len(plan.container_candidates)}",
        ]
        if plan.container_candidates:
            lines.append("container candidates:")
            for idx, item in enumerate(plan.container_candidates[:20], start=1):
                lines.append(f"{idx}. {item}")
        else:
            lines.append("container candidates: none")

        lines.append("")
        lines.append("command preview:")
        lines.append(plan.command_preview)
        if plan.message:
            lines.append("")
            lines.append(plan.message)

        self._set_import_preview("\n".join(lines).strip())
        self.status_label.config(text="🧩 Extract plan подготовлен", foreground="green")

    def on_run_extract(self):
        if self.extract_in_progress:
            return

        if not self.extract_plan or not getattr(self.extract_plan, "success", False):
            messagebox.showwarning("Extract", "Сначала выполните 'Подготовить extract'.")
            return

        tool_path = (self.extractor_tool_var.get() or "").strip()
        if not tool_path:
            messagebox.showwarning("Extract", "Укажите путь к extractor tool.")
            return

        template = (self.extractor_command_template_var.get() or "").strip() or DEFAULT_COMMAND_TEMPLATE
        container = (self.extract_container_var.get() or "").strip() or self.extract_plan.selected_container
        if not container:
            messagebox.showwarning("Extract", "Выберите container candidate.")
            return

        output_dir = (self.extractor_output_dir_var.get() or "").strip()
        if not output_dir:
            output_dir = getattr(config, "UE_EXTRACTOR_OUTPUT_DIR", os.path.join(config.CONFIG_DIR, "extracted_resources"))
            self.extractor_output_dir_var.set(output_dir)

        self.extract_plan.output_dir = os.path.abspath(os.path.expanduser(output_dir))
        self.extract_plan.expected_output_path = UEResourceExtractor.build_expected_output_path(
            self.extract_plan.output_dir,
            self.extract_plan.internal_path,
        )
        self.extract_plan.selected_container = container
        self.extract_plan.command_template = template
        self.extract_plan.command_preview = UEResourceExtractor.build_command_preview(
            tool=(tool_path or "<tool>"),
            container=(container or "<container>"),
            output_dir=(self.extract_plan.output_dir or "<output_dir>"),
            internal_path=self.extract_plan.internal_path,
            game_root=(self.extract_plan.game_root or "<game_root>"),
            expected_output_path=(self.extract_plan.expected_output_path or "<expected_output_path>"),
            command_template=template,
        )

        self._persist_extractor_settings()

        self._start_extract_execution(
            tool_path=tool_path,
            container=container,
            template=template,
            request_mode="manual",
            request_root_norm=self._normalized_path((self.game_root_var.get() or "").strip()),
            request_candidate_key="",
        )

    def _run_extract_worker(self, tool_path: str, container: str, template: str):
        try:
            result = UEResourceExtractor.run_extraction(
                plan=self.extract_plan,
                tool_path=tool_path,
                container_path=container,
                command_template=template,
                timeout_sec=180,
            )
            self.root.after(0, self._on_extract_done, result)
        except Exception as exc:
            self.root.after(0, self._on_extract_failed, str(exc))

    def _on_extract_failed(self, error_text: str):
        self.extract_in_progress = False
        self._extract_request_mode = "manual"
        self._extract_request_root_norm = ""
        self._extract_request_candidate_key = ""
        self.btn_run_extract.config(state=tk.NORMAL)
        self.btn_prepare_extract.config(state=tk.NORMAL)
        self.status_label.config(text="❌ Ошибка extract", foreground="red")
        self._set_import_preview(f"Ошибка external extract: {error_text}")
        log(f"❌ Ошибка external extract: {error_text}", level="ERROR")
        self._run_pending_auto_scan_if_idle()

    def _on_extract_done(self, result):
        request_mode = self._extract_request_mode
        request_root_norm = self._extract_request_root_norm
        request_candidate_key = self._extract_request_candidate_key
        self.extract_in_progress = False
        self._extract_request_mode = "manual"
        self._extract_request_root_norm = ""
        self._extract_request_candidate_key = ""
        self.btn_run_extract.config(state=tk.NORMAL)
        self.btn_prepare_extract.config(state=tk.NORMAL)

        lines = [
            "Extraction result:",
            f"success: {result.success}",
            f"message: {result.message}",
            f"container: {result.selected_container}",
            f"expected output: {result.expected_output_path}",
            f"resolved file: {result.extracted_file or '-'}",
            "",
            "command:",
            result.command_preview,
        ]

        if result.stdout_tail:
            lines.extend(["", "stdout (tail):", result.stdout_tail])
        if result.stderr_tail:
            lines.extend(["", "stderr (tail):", result.stderr_tail])

        self._set_import_preview("\n".join(lines).strip())

        if not result.success:
            self.status_label.config(text="⚠️ Extract завершен с ошибкой", foreground="orange")
            log(f"⚠️ External extract failed: {result.message}", level="WARNING")
            self._run_pending_auto_scan_if_idle()
            return

        if result.extracted_file:
            self.import_file_var.set(result.extracted_file)

        self.status_label.config(text="🟢 Extract завершен", foreground="green")
        log(f"✅ External extract success: {result.extracted_file}", level="INFO")

        # Reuse existing import pipeline to make extracted file ready for run.
        if result.extracted_file:
            if request_mode == "auto":
                current_root_norm = self._normalized_path((self.game_root_var.get() or "").strip())
                if request_root_norm and current_root_norm and request_root_norm != current_root_norm:
                    self.status_label.config(text="ℹ️ Авто-импорт пропущен: активная игра изменилась", foreground="orange")
                    log("ℹ️ Авто-импорт после extract пропущен: game_root изменился", level="INFO")
                else:
                    imported = self._import_subtitle_resource_target(result.extracted_file, auto_mode=True)
                    if imported:
                        self._auto_last_imported_root_norm = request_root_norm
                        self._auto_last_imported_candidate_key = request_candidate_key
            else:
                self.on_import_subtitle_resource()

        self._run_pending_auto_scan_if_idle()

    def on_scan_sources(self):
        if self.scan_in_progress:
            return

        game_root = (self.game_root_var.get() or "").strip()
        if not game_root:
            messagebox.showwarning("Сканер", "Укажите папку игры")
            return
        if not os.path.isdir(game_root):
            messagebox.showwarning("Сканер", f"Папка не найдена: {game_root}")
            return

        self._start_scan_sources(
            game_root,
            request_mode="manual",
            request_root_norm=self._normalized_path(game_root),
        )

    def _scan_sources_worker(self, game_root: str, request_mode: str):
        try:
            display_limit = int(getattr(config, "SCAN_RESULT_LIMIT", 30))
            auto_limit = int(getattr(config, "AUTO_SCAN_RESULT_LIMIT", max(display_limit, 300)))
            result = self.subtitle_scanner.scan(
                game_root=game_root,
                result_limit=auto_limit if request_mode == "auto" else display_limit,
            )
            self.root.after(0, self._on_scan_sources_done, result)
        except Exception as e:
            self.root.after(0, self._on_scan_sources_failed, str(e))

    def _on_scan_sources_done(self, result: dict):
        request_mode = self._scan_request_mode
        request_root_norm = self._scan_request_root_norm
        self.scan_in_progress = False
        self._scan_request_mode = "manual"
        self._scan_request_root_norm = ""
        self.btn_scan_sources.config(state=tk.NORMAL)

        lines = []
        visited = int(result.get("visited_files", 0))
        max_files = int(result.get("max_files", 0))
        stopped_by_limit = bool(result.get("stopped_by_limit", False))
        roots = result.get("roots", [])
        candidates = result.get("candidates", [])
        self._update_scan_candidates(candidates)

        lines.append(f"Просканировано файлов: {visited}/{max_files}")
        if stopped_by_limit:
            lines.append("Достигнут лимит сканирования. Увеличьте SCAN_MAX_FILES при необходимости.")
        lines.append(f"Корней поиска: {len(roots)}")
        lines.append("")

        if not candidates:
            lines.append("Подходящих кандидатов не найдено.")
        else:
            lines.append("Топ кандидатов (по убыванию score):")
            lines.append("")
            for idx, item in enumerate(candidates, start=1):
                kind = item.get("kind", "unknown")
                readable = "читаемо" if kind == "text-log" else "требует распаковки/парсинга"
                lines.append(
                    f"{idx}. [{item.get('score', 0)}] {kind} ({readable})"
                )
                lines.append(f"   path: {item.get('path', '')}")
                lines.append(f"   reason: {item.get('reason', '')}")
                lines.append("")

        self._set_scan_output("\n".join(lines).strip())
        self.status_label.config(text="🟢 Сканирование завершено", foreground="green")
        log(f"🔎 Сканирование источников завершено, кандидатов: {len(candidates)}", level="INFO")

        if request_mode == "auto":
            self._auto_scan_inflight_root_norm = ""
            self._run_auto_best_candidate_pipeline(candidates, request_root_norm)

        self._run_pending_auto_scan_if_idle()

    def _on_scan_sources_failed(self, error_text: str):
        self.scan_in_progress = False
        request_mode = self._scan_request_mode
        self._scan_request_mode = "manual"
        self._scan_request_root_norm = ""
        if request_mode == "auto":
            self._auto_scan_inflight_root_norm = ""
        self.btn_scan_sources.config(state=tk.NORMAL)
        self._set_scan_output(f"Ошибка сканирования: {error_text}")
        self.status_label.config(text="❌ Ошибка сканирования", foreground="red")
        log(f"❌ Ошибка сканирования источников: {error_text}", level="ERROR")
        self._run_pending_auto_scan_if_idle()

    def _set_scan_output(self, text: str):
        self.scan_results_text.config(state=tk.NORMAL)
        self.scan_results_text.delete("1.0", tk.END)
        self.scan_results_text.insert("1.0", text)
        self.scan_results_text.config(state=tk.DISABLED)

    def _set_import_preview(self, text: str):
        self.import_preview_text.config(state=tk.NORMAL)
        self.import_preview_text.delete("1.0", tk.END)
        self.import_preview_text.insert("1.0", text)
        self.import_preview_text.config(state=tk.DISABLED)

    def _update_scan_candidates(self, candidates: list[dict]):
        self.scan_candidates = list(candidates or [])
        self.scan_candidate_map = {}
        self.extract_plan = None
        self._set_extract_candidates([])
        labels = []

        for idx, item in enumerate(self.scan_candidates, start=1):
            path = str(item.get("path", "") or "").strip()
            if not path:
                continue

            score = item.get("score", 0)
            kind = item.get("kind", "unknown")
            label = f"{idx}. [{score}] {kind} :: {path}"
            labels.append(label)
            self.scan_candidate_map[label] = path

        self.scan_candidate_labels = labels
        self.combo_scan_candidate["values"] = tuple(labels)

        if labels:
            self.scan_candidate_var.set(labels[0])
        else:
            self.scan_candidate_var.set("")

    def _resolve_import_target(self) -> str:
        manual_path = (self.import_file_var.get() or "").strip()
        if manual_path:
            return manual_path

        selected_label = (self.scan_candidate_var.get() or "").strip()
        if selected_label:
            return self.scan_candidate_map.get(selected_label, "")

        return ""

    def _import_subtitle_resource_target(self, target: str, auto_mode: bool = False) -> bool:
        normalized_target = (target or "").strip()
        if not normalized_target:
            return False

        result = import_subtitle_resource(normalized_target)
        if not result.ok:
            self.imported_subtitles = []
            self.imported_source = ""
            self.imported_source_type = ""
            self._set_import_preview(result.error_message)
            self.status_label.config(text="⚠️ Импорт не выполнен", foreground="orange")
            log(f"⚠️ Импорт ресурса не выполнен: {result.error_message}", level="WARNING")
            return False

        self.imported_subtitles = list(result.lines)
        self.imported_source = result.source
        self.imported_source_type = result.source_type

        preview_lines = [
            f"Источник: {result.source}",
            f"Тип: {result.source_type}",
            f"Строк: {result.line_count}",
            "",
        ]
        if result.preview_lines:
            preview_lines.append("Preview:")
            for idx, line in enumerate(result.preview_lines, start=1):
                preview_lines.append(f"{idx}. {line}")
        else:
            preview_lines.append("Файл импортирован, но строки не извлечены.")

        self._set_import_preview("\n".join(preview_lines).strip())
        self.status_label.config(text=f"🟢 Импортировано строк: {result.line_count}", foreground="green")
        log(
            f"✅ Импорт ресурса завершён: type={result.source_type}, lines={result.line_count}",
            level="INFO",
        )
        return True

    def on_import_subtitle_resource(self):
        target = self._resolve_import_target()
        if not target:
            messagebox.showwarning(
                "Импорт",
                "Выберите кандидата из scan или укажите локальный файл для импорта.",
            )
            return

        self._import_subtitle_resource_target(target, auto_mode=False)

    def on_copy_scan_results(self):
        text = self.scan_results_text.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        self.status_label.config(text="🟢 Результаты скопированы", foreground="green")

    def _push_text_to_comparison_queue(self, text: str, keep_latest: bool | None = None) -> bool:
        cleaned = (text or "").strip()
        if not cleaned:
            return False

        if keep_latest is None:
            keep_latest = bool(getattr(config, "TEXT_COMPARISON_KEEP_LATEST", True))

        if keep_latest:
            while not Queues.text_comparison_queue.empty():
                try:
                    Queues.text_comparison_queue.get_nowait()
                except Empty:
                    break

        try:
            Queues.text_comparison_queue.put_nowait(cleaned)
            return True
        except Full:
            if keep_latest:
                try:
                    Queues.text_comparison_queue.get_nowait()
                except Empty:
                    pass
                try:
                    Queues.text_comparison_queue.put_nowait(cleaned)
                    return True
                except Full:
                    return False

            while ThreadLifecycle.is_pipeline_running():
                try:
                    Queues.text_comparison_queue.put_nowait(cleaned)
                    return True
                except Full:
                    time.sleep(0.01)

        return False

    def _imported_subtitles_loop(self):
        if not self.imported_subtitles:
            return

        line_delay = float(getattr(config, "IMPORT_SUBTITLE_LINE_DELAY", 0.20))
        log(
            f"📥 Импортированный источник запущен: строк={len(self.imported_subtitles)}",
            level="INFO",
        )

        for line in self.imported_subtitles:
            if not ThreadLifecycle.is_pipeline_running():
                break

            while ThreadLifecycle.is_pipeline_running() and ThreadLifecycle.is_paused:
                time.sleep(0.05)

            if not ThreadLifecycle.is_pipeline_running():
                break

            self._push_text_to_comparison_queue(line, keep_latest=False)
            time.sleep(max(0.01, line_delay))

        log("⏹️ Импортированный источник завершён", level="INFO")

    def on_start_work(self):
        if self.is_running:
            messagebox.showwarning("Внимание", "Уже запущено")
            return

        if not self.imported_subtitles:
            self.status_label.config(
                text="⚠️ Нет импортированных строк: сначала выполните поиск/импорт субтитров",
                foreground="orange",
            )
            log("ℹ️ Старт пропущен: импортированные строки отсутствуют", level="INFO")
            messagebox.showwarning(
                "Начать",
                "Нет импортированных строк. Сначала найдите/импортируйте субтитры "
                "или дождитесь автоимпорта.",
            )
            return

        try:
            self.audio_cache.clear()
            self.history.clear()
            log("🗑️ Кеш и история очищены в начале сессии", level="INFO")

            ThreadLifecycle.start_session()
            self.is_running = True
            self.is_paused = False

            self.text_comp_worker = TextComparisonWorker(self.audio_player, self.translator)
            self.audio_prep_worker = AudioPrepWorker(self.tts_engine, self.audio_cache)
            self.audio_prep_worker.set_speed(config.TTS_SPEED_DEFAULT)
            self.audio_prep_dispatcher = AudioPrepDispatcher(self.audio_prep_worker)
            self.playback_worker = PlaybackWorker(self.audio_player)

            self.threads = []
            worker_targets = [
                ("TextComparison", self.text_comp_worker.run),
                ("AudioPrepDispatcher", self.audio_prep_dispatcher.run),
                ("Playback", self.playback_worker.run),
                ("ImportedSource", self._imported_subtitles_loop),
            ]

            self.import_source_thread = None

            for name, target in worker_targets:
                t = threading.Thread(name=name, target=target, daemon=True)
                t.start()
                self.threads.append(t)
                log(f"✅ Поток {name} запущен", level="DEBUG")

                if name == "ImportedSource":
                    self.import_source_thread = t

            self._update_ui_running()
            imported_type = self.imported_source_type or "import"
            self.status_label.config(text=f"🔴 Импорт активен ({imported_type})", foreground="red")
            log("🚀 Импортированный источник запущен", level="INFO")

        except Exception as e:
            ThreadLifecycle.stop_session()
            self.is_running = False
            log(f"❌ Ошибка запуска: {e}", level="ERROR")
            messagebox.showerror("Ошибка", f"Не удалось запустить: {e}")

    def on_stop_work(self):
        try:
            log("🛑 Останавливаем import/TTS pipeline...", level="INFO")
            ThreadLifecycle.stop_session()
            self.audio_player.stop()
            self.is_running = False
            self.is_paused = False

            # Быстро очищаем конвейер, чтобы после Stop не доигрывались хвосты.
            Queues.clear_all()

            join_timeout = float(getattr(config, "THREAD_STOP_JOIN_TIMEOUT", 4.0))
            join_deadline = time.time() + max(0.1, join_timeout)
            for t in self.threads:
                remaining = max(0.0, join_deadline - time.time())
                if remaining <= 0:
                    break
                t.join(timeout=remaining)

            alive_threads = [t.name for t in self.threads if t.is_alive()]
            if alive_threads:
                log(
                    f"⚠️ Не все потоки завершились за {join_timeout:.1f}s: {', '.join(alive_threads)}",
                    level="WARNING",
                )

            self.threads.clear()

            Queues.clear_all()
            self.audio_player.stop()
            self._update_ui_stopped()
            self.status_label.config(text="🟢 Готово", foreground="green")
            log("✅ Pipeline остановлен", level="INFO")

        except Exception as e:
            self.is_running = False
            log(f"❌ Ошибка остановки: {e}", level="ERROR")
            messagebox.showerror("Ошибка", f"Ошибка остановки: {e}")

    def on_pause(self):
        if not self.is_running:
            return

        self.is_paused = not self.is_paused
        if self.is_paused:
            ThreadLifecycle.pause()
            Queues.clear_all()
            self.audio_player.pause()
            self.btn_pause.config(text="▶ Продолжить")
            self.status_label.config(text="⏸ Пауза", foreground="orange")
        else:
            ThreadLifecycle.unpause()
            self.audio_player.unpause()
            self.btn_pause.config(text="⏸ Пауза")
            self.status_label.config(text="🔴 Импорт активен", foreground="red")
            log("▶️ Pipeline продолжен", level="INFO")

    def on_apply_languages(self):
        read_label = (self.read_language_var.get() or "").strip()
        speech_label = (self.speech_language_var.get() or "").strip()

        read_code = self.lang_label_to_code.get(read_label)
        speech_code = self.lang_label_to_code.get(speech_label)

        if read_code is None or speech_code is None:
            messagebox.showwarning("Языки", "Выберите корректные языки")
            return

        if speech_code == "auto":
            messagebox.showwarning("Языки", "Для озвучки выберите конкретный язык")
            return

        try:
            self.read_lang_code = read_code
            self.speech_lang_code = speech_code

            config.TRANSLATOR_SOURCE_LANG = read_code
            config.TRANSLATOR_TARGET_LANG = speech_code
            self.translator.set_languages(read_code, speech_code)

            # Сохраняем пользовательский голос, если он доступен для выбранного языка.
            voice_options = getattr(config, "TTS_VOICE_OPTIONS", {}).get(speech_code, [])
            allowed_voice_ids = {voice_id for voice_id, _ in voice_options}

            selected_label = (self.voice_var.get() or "").strip()
            selected_from_combo = self.voice_label_to_id.get(selected_label)
            current_voice = getattr(config, "TTS_VOICE", "")
            saved_voice = self.settings.get("tts_voice", "")
            default_voice = getattr(config, "TTS_VOICE_BY_LANGUAGE", {}).get(speech_code)

            preferred_voice = None
            for candidate in (selected_from_combo, current_voice, saved_voice, default_voice):
                if not candidate:
                    continue
                if not allowed_voice_ids or candidate in allowed_voice_ids:
                    preferred_voice = candidate
                    break

            if preferred_voice:
                config.TTS_VOICE = preferred_voice
                self.tts_engine.set_voice(preferred_voice)
                self.settings.set("tts_voice", preferred_voice)

            self._refresh_voice_options(speech_code, select_voice=preferred_voice or config.TTS_VOICE)

            # Кеш аудио зависит от голоса и языка, очищаем чтобы не проигрывать старые варианты.
            self.audio_cache.clear()

            self.settings.set("read_language", read_code)
            self.settings.set("speech_language", speech_code)

            same_lang = (read_code != "auto" and read_code == speech_code)
            if same_lang:
                self.status_label.config(text="🟢 Языки совпадают: перевод выключен", foreground="green")
                log(f"✅ Языки применены: {read_label} → {speech_label} (без перевода)", level="INFO")
            else:
                self.status_label.config(text=f"🟢 Языки: {read_label} → {speech_label}", foreground="green")
                log(f"✅ Языки применены: {read_label} → {speech_label}", level="INFO")
        except Exception as e:
            log(f"❌ Ошибка применения языков: {e}", level="ERROR")
            messagebox.showerror("Ошибка", f"Не удалось применить языки: {e}")

    def _refresh_voice_options(self, speech_code: str, select_voice: str | None = None):
        options = getattr(config, "TTS_VOICE_OPTIONS", {}).get(speech_code, [])
        if not options:
            fallback = getattr(config, "TTS_VOICE_BY_LANGUAGE", {}).get(speech_code)
            if fallback:
                options = [(fallback, fallback)]

        self.voice_id_to_label = {voice_id: label for voice_id, label in options}
        self.voice_label_to_id = {label: voice_id for voice_id, label in options}

        labels = [label for _, label in options]
        self.combo_voice["values"] = tuple(labels)

        chosen_voice = select_voice or getattr(config, "TTS_VOICE", "")
        chosen_label = self.voice_id_to_label.get(chosen_voice)
        if chosen_label:
            self.voice_var.set(chosen_label)
        elif labels:
            self.voice_var.set(labels[0])
        else:
            self.voice_var.set("")

    def on_apply_voice(self):
        voice_label = (self.voice_var.get() or "").strip()
        voice_id = self.voice_label_to_id.get(voice_label)
        if not voice_id:
            messagebox.showwarning("Голос", "Выберите голос из списка")
            return

        try:
            config.TTS_VOICE = voice_id
            self.tts_engine.set_voice(voice_id)
            self.audio_cache.clear()
            self.settings.set("tts_voice", voice_id)
            self.status_label.config(text=f"🟢 Голос: {voice_label}", foreground="green")
            log(f"✅ Голос применён: {voice_id}", level="INFO")
        except Exception as e:
            log(f"❌ Ошибка применения голоса: {e}", level="ERROR")
            messagebox.showerror("Ошибка", f"Не удалось применить голос: {e}")

    def on_show_history(self):
        phrases = self.history.get_all()
        text = "История фраз:\n" + "\n".join(phrases[-100:])

        win = tk.Toplevel(self.root)
        win.title("История")
        win.geometry("520x360")
        box = tk.Text(win, wrap=tk.WORD)
        box.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        box.insert(1.0, text)
        box.config(state=tk.DISABLED)

    def on_clear_cache(self):
        if messagebox.askyesno("Подтверждение", "Очистить кеш аудио?"):
            self.audio_cache.clear()
            messagebox.showinfo("Успех", "Кеш очищен")
            log("🗑️ Кеш очищен", level="INFO")

    def on_show_logs(self):
        try:
            with open(config.LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                logs = f.read()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть логи: {e}")
            return

        win = tk.Toplevel(self.root)
        win.title("Логи")
        win.geometry("700x420")
        box = tk.Text(win, wrap=tk.WORD)
        box.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        box.insert(1.0, "\n".join(logs.splitlines()[-200:]))
        box.config(state=tk.DISABLED)

    def _on_closing(self):
        if self.is_running and not messagebox.askyesno("Подтверждение", "Остановить pipeline и выйти?"):
            return

        try:
            if self._game_autodetect_after_id:
                try:
                    self.root.after_cancel(self._game_autodetect_after_id)
                except Exception:
                    pass
                self._game_autodetect_after_id = None
            self.on_stop_work()
        finally:
            try:
                self.audio_player.cleanup()
            except Exception:
                pass
            self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = MainWindow()
    app.run()
