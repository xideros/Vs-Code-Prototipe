# ui/__init__.py - Главное окно приложения

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from contextlib import nullcontext
import numpy as np
from queue import Empty, Full

import mss
from PIL import Image as PILImage, ImageTk

import config
from core import AudioPlayer, OCREngine, TTSEngine, TextTranslator
from storage import AudioCache, HistoryManager, ROIConfig, SettingsManager
from threading_workers import (
    AudioPrepDispatcher,
    AudioPrepWorker,
    OCRWorker,
    PlaybackWorker,
    Queues,
    TextComparisonWorker,
    ThreadLifecycle,
)
from utils.logger import log


class MainWindow:
    """Новый компактный UI поверх существующего OCR/TTS пайплайна."""

    def __init__(self):
        self.root = tk.Tk()
        self._configure_styles()
        self.root.title(config.WINDOW_TITLE)
        self.root.resizable(config.WINDOW_RESIZABLE, config.WINDOW_RESIZABLE)
        self.root.minsize(config.WINDOW_WIDTH, config.WINDOW_HEIGHT)

        self.profile_key_to_label = {
            "realtime": "Быстрый",
            "balanced": "Сбалансированный",
            "quality": "Качественный",
        }
        self.profile_label_to_key = {
            value: key for key, value in self.profile_key_to_label.items()
        }
        self.lang_code_to_label = dict(getattr(config, "LANGUAGE_OPTIONS", []))
        self.lang_label_to_code = {v: k for k, v in self.lang_code_to_label.items()}
        self.voice_id_to_label = {}
        self.voice_label_to_id = {}

        self.settings = SettingsManager()
        saved_profile = self.settings.get("ocr_profile", getattr(config, "OCR_PROFILE", "balanced"))
        if saved_profile in self.profile_key_to_label:
            config.OCR_PROFILE = saved_profile
        elif saved_profile in self.profile_label_to_key:
            config.OCR_PROFILE = self.profile_label_to_key[saved_profile]

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
        self.ocr_engine = OCREngine()
        self.tts_engine = TTSEngine()
        self.translator = TextTranslator()
        self.audio_player = AudioPlayer()
        self.audio_cache = AudioCache()
        self.history = HistoryManager()
        self.roi_config = ROIConfig()

        saved_volume = self.settings.get("volume", getattr(config, "AUDIO_VOLUME_DEFAULT", 70))
        try:
            self.audio_player.set_volume(int(saved_volume))
        except Exception:
            pass

        # Worker-ссылки
        self.ocr_worker = None
        self.text_comp_worker = None
        self.audio_prep_worker = None
        self.audio_prep_dispatcher = None
        self.playback_worker = None
        self.threads = []

        # Состояние UI
        self.is_running = False
        self.is_paused = False
        profile_label = self.profile_key_to_label.get(config.OCR_PROFILE, "Сбалансированный")
        self.ocr_profile_var = tk.StringVar(value=profile_label)
        self.read_language_var = tk.StringVar(value=self.lang_code_to_label.get(self.read_lang_code, "Авто"))
        self.speech_language_var = tk.StringVar(value=self.lang_code_to_label.get(self.speech_lang_code, "Русский"))
        self.voice_var = tk.StringVar(value="")
        self._cv2 = self._try_import_cv2()
        self._auto_subtitle_state = {
            "frame_idx": 0,
            "y": None,
            "h": None,
        }

        self._build_ui()
        self._refresh_voice_options(self.speech_lang_code, select_voice=config.TTS_VOICE)
        self._apply_initial_geometry()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        log("✅ MainWindow инициализирована успешно", level="INFO")

    def _try_import_cv2(self):
        try:
            import cv2

            return cv2
        except Exception:
            return None

    def _auto_crop_subtitle_band(self, frame):
        """Автопоиск полосы субтитров по плотности контуров текста."""
        if frame is None:
            return frame
        if not bool(getattr(config, "AUTO_SUBTITLE_DETECT_ENABLED", True)):
            return frame
        if self._cv2 is None:
            return frame

        cv2 = self._cv2
        h, w = frame.shape[:2]
        if h < 40 or w < 120:
            return frame

        scan_top = int(h * float(getattr(config, "AUTO_SUBTITLE_SCAN_TOP_RATIO", 0.40)))
        scan_bottom = int(h * float(getattr(config, "AUTO_SUBTITLE_SCAN_BOTTOM_RATIO", 0.98)))
        band_h = int(h * float(getattr(config, "AUTO_SUBTITLE_BAND_HEIGHT_RATIO", 0.22)))
        margin = int(w * float(getattr(config, "AUTO_SUBTITLE_SIDE_MARGIN_RATIO", 0.06)))
        re_detect_every = int(getattr(config, "AUTO_SUBTITLE_REDETECT_EVERY", 10))
        smoothing = float(getattr(config, "AUTO_SUBTITLE_SMOOTHING", 0.60))
        warmup_frames = int(getattr(config, "AUTO_SUBTITLE_WARMUP_FRAMES", 20))
        min_edge_density = float(getattr(config, "AUTO_SUBTITLE_MIN_EDGE_DENSITY", 0.012))
        max_jump_ratio = float(getattr(config, "AUTO_SUBTITLE_MAX_JUMP_RATIO", 0.18))

        scan_top = max(0, min(scan_top, h - 2))
        scan_bottom = max(scan_top + 2, min(scan_bottom, h))
        band_h = max(24, min(band_h, scan_bottom - scan_top))

        self._auto_subtitle_state["frame_idx"] += 1
        frame_idx = self._auto_subtitle_state["frame_idx"]
        need_re_detect = (
            self._auto_subtitle_state["y"] is None
            or frame_idx <= max(1, warmup_frames)
            or frame_idx % max(1, re_detect_every) == 0
        )

        if need_re_detect:
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            roi_gray = gray[scan_top:scan_bottom, :]
            edges = cv2.Canny(roi_gray, 80, 180)
            # Доля edge-пикселей по строкам: устойчивее к смене сцены.
            proj = (edges > 0).mean(axis=1).astype(np.float32)

            win = np.ones(band_h, dtype=np.float32) / float(max(1, band_h))
            score = np.convolve(proj, win, mode="valid")
            if score.size > 0:
                best_local_y = int(np.argmax(score))
                best_density = float(score[best_local_y])

                # Если текстовой сигнал слабый, не режем ROI автоматически.
                if best_density < min_edge_density:
                    return frame

                detected_y = scan_top + best_local_y

                prev_y = self._auto_subtitle_state.get("y")
                if prev_y is None:
                    smoothed_y = detected_y
                else:
                    max_jump = int(h * max_jump_ratio)
                    if abs(detected_y - prev_y) > max_jump:
                        detected_y = prev_y + max_jump if detected_y > prev_y else prev_y - max_jump
                    smoothed_y = int(prev_y * smoothing + detected_y * (1.0 - smoothing))

                self._auto_subtitle_state["y"] = smoothed_y
                self._auto_subtitle_state["h"] = band_h

        y0 = self._auto_subtitle_state.get("y")
        bh = self._auto_subtitle_state.get("h") or band_h
        if y0 is None:
            return frame

        y0 = max(scan_top, min(y0, scan_bottom - bh))
        x0 = max(0, margin)
        x1 = min(w, w - margin)
        if x1 - x0 < 60:
            x0, x1 = 0, w

        return frame[y0:y0 + bh, x0:x1]

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
            padding=(10, 6)
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

        container = ttk.Frame(self.root, padding=20)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)

        # Заголовок
        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        ttk.Label(header, text="Game Subtitle Assistant", style="Header.TLabel").pack(side="left")

        # --- Блок Управления ---
        controls = ttk.LabelFrame(container, text="Управление", padding=(15, 10))
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 15))
        controls.columnconfigure((0, 1, 2), weight=1)

        self.btn_start = ttk.Button(controls, text="▶ Начать", command=self.on_start_work, style="Accent.TButton")
        self.btn_stop = ttk.Button(controls, text="■ Стоп", command=self.on_stop_work, state=tk.DISABLED)
        self.btn_pause = ttk.Button(controls, text="⏸ Пауза", command=self.on_pause, state=tk.DISABLED)

        self.btn_start.grid(row=0, column=0, padx=5, sticky="ew")
        self.btn_stop.grid(row=0, column=1, padx=5, sticky="ew")
        self.btn_pause.grid(row=0, column=2, padx=5, sticky="ew")

        # --- Выбор региона (ROI) ---
        roi_box = ttk.LabelFrame(container, text="Регион субтитров", padding=(15, 10))
        roi_box.grid(row=2, column=0, sticky="ew", pady=(0, 15))
        roi_box.columnconfigure(1, weight=1)

        self.btn_select_roi = ttk.Button(roi_box, text="🖱 Выбрать регион", command=self.on_select_roi)
        self.btn_select_roi.grid(row=0, column=0, padx=(0, 10), sticky="w")

        self.label_roi_status = ttk.Label(roi_box, text="ROI не выбран", style="Error.TLabel")
        self.label_roi_status.grid(row=0, column=1, sticky="w")

        # --- OCR Профиль ---
        profile_box = ttk.LabelFrame(container, text="Настройки OCR", padding=(15, 10))
        profile_box.grid(row=3, column=0, sticky="ew", pady=(0, 15))
        profile_box.columnconfigure(1, weight=1)

        ttk.Label(profile_box, text="Режим:").grid(row=0, column=0, padx=(0, 10), sticky="w")
        self.combo_ocr_profile = ttk.Combobox(
            profile_box, 
            textvariable=self.ocr_profile_var, 
            values=("Быстрый", "Сбалансированный", "Качественный"), 
            state="readonly"
        )
        self.combo_ocr_profile.grid(row=0, column=1, sticky="ew")
        
        ttk.Button(profile_box, text="Применить", command=self.on_apply_ocr_profile, width=12).grid(row=0, column=2, padx=(10, 0), sticky="e")

        # --- Языки и Голос ---
        lang_box = ttk.LabelFrame(container, text="Языки и Озвучка", padding=(15, 10))
        lang_box.grid(row=4, column=0, sticky="ew", pady=(0, 15))
        lang_box.columnconfigure(1, weight=1)

        # Чтение
        ttk.Label(lang_box, text="Чтение:").grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.combo_read_language = ttk.Combobox(
            lang_box, 
            textvariable=self.read_language_var, 
            values=tuple(self.lang_code_to_label.values()), 
            state="readonly"
        )
        self.combo_read_language.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=(0, 10))
        
        # Общая кнопка применить для языков
        ttk.Button(lang_box, text="Применить", command=self.on_apply_languages, width=12).grid(
            row=0, column=2, rowspan=2, padx=(10, 0), sticky="ns"
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
        self.combo_speech_language.grid(row=1, column=1, sticky="ew", padx=(10, 0))

        # Голос (отдельная строка)
        ttk.Label(lang_box, text="Голос:").grid(row=2, column=0, sticky="w", pady=(15, 0))
        self.combo_voice = ttk.Combobox(
            lang_box,
            textvariable=self.voice_var,
            values=(),
            state="readonly"
        )
        self.combo_voice.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=(15, 0))
        
        ttk.Button(lang_box, text="Обновить", command=self.on_apply_voice, width=12).grid(
            row=2, column=2, padx=(10, 0), pady=(15, 0), sticky="e"
        )

        # --- Инструменты ---
        tools_frame = ttk.Frame(container)
        tools_frame.grid(row=5, column=0, sticky="ew", pady=(0, 15))
        
        ttk.Button(tools_frame, text="Очистить кеш", command=self.on_clear_cache).pack(side="left", padx=(0, 10))
        ttk.Button(tools_frame, text="Логи", command=self.on_show_logs).pack(side="left")

        # --- Статус бар ---
        status_box = ttk.LabelFrame(container, text="Статус", padding=(10, 5))
        status_box.grid(row=6, column=0, sticky="ew")
        status_box.columnconfigure(0, weight=1)
        
        self.status_label = ttk.Label(status_box, text="🟢 Готово", foreground="#6ec273", font=("Segoe UI", 10, "bold"))
        self.status_label.grid(row=0, column=0, sticky="w")

        roi = self.roi_config.get()
        if roi:
            self.label_roi_status.config(
                text=f"ROI: ({roi[0]}, {roi[1]}) {roi[2]}x{roi[3]}",
                foreground="#6ec273",
                style="Status.TLabel"
            )

    def _apply_initial_geometry(self):
        self.root.update_idletasks()

        req_width = self.root.winfo_reqwidth()
        req_height = self.root.winfo_reqheight()
        width = max(config.WINDOW_WIDTH, req_width + 24)
        height = max(config.WINDOW_HEIGHT, req_height + 24)

        self.root.minsize(width, height)
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _update_ui_running(self):
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_pause.config(state=tk.NORMAL)
        self.btn_select_roi.config(state=tk.DISABLED)

    def _update_ui_stopped(self):
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_pause.config(state=tk.DISABLED, text="⏸ Пауза")
        self.btn_select_roi.config(state=tk.NORMAL)

    def on_start_work(self):
        if self.is_running:
            messagebox.showwarning("Внимание", "Уже запущено")
            return

        if not self.roi_config.is_configured():
            messagebox.showwarning("Внимание", "Сначала выберите регион субтитров")
            self.on_select_roi()
            return

        try:
            self.audio_cache.clear()
            self.history.clear()
            log("🗑️ Кеш и история очищены в начале сессии", level="INFO")

            ThreadLifecycle.start_session()
            self.is_running = True
            self.is_paused = False

            self.ocr_worker = OCRWorker(self.ocr_engine, self.translator)
            self.text_comp_worker = TextComparisonWorker(self.audio_player, self.translator)
            self.audio_prep_worker = AudioPrepWorker(self.tts_engine, self.audio_cache)
            self.audio_prep_worker.set_speed(config.TTS_SPEED_DEFAULT)
            self.audio_prep_dispatcher = AudioPrepDispatcher(self.audio_prep_worker)
            self.playback_worker = PlaybackWorker(self.audio_player)

            self.threads = []
            for name, target in [
                ("OCR", self.ocr_worker.run),
                ("TextComparison", self.text_comp_worker.run),
                ("AudioPrepDispatcher", self.audio_prep_dispatcher.run),
                ("Playback", self.playback_worker.run),
                ("ScreenCapture", self._screenshot_loop),
            ]:
                t = threading.Thread(name=name, target=target, daemon=True)
                t.start()
                self.threads.append(t)
                log(f"✅ Поток {name} запущен", level="DEBUG")

            self._update_ui_running()
            self.status_label.config(text="🔴 Захват активен", foreground="red")
            log("🚀 Захват запущен", level="INFO")

        except Exception as e:
            ThreadLifecycle.stop_session()
            self.is_running = False
            log(f"❌ Ошибка запуска: {e}", level="ERROR")
            messagebox.showerror("Ошибка", f"Не удалось запустить: {e}")

    def on_stop_work(self):
        try:
            log("🛑 Останавливаем захват...", level="INFO")
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
            log("✅ Захват остановлен", level="INFO")

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
            self.status_label.config(text="🔴 Захват активен", foreground="red")
            log("▶️ Захват продолжен", level="INFO")

    def on_apply_ocr_profile(self):
        selected_label = (self.ocr_profile_var.get() or "").strip()
        selected_key = self.profile_label_to_key.get(selected_label)
        if selected_key is None:
            messagebox.showwarning("Профиль OCR", "Выберите корректный профиль")
            return

        if selected_key == getattr(config, "OCR_PROFILE", "balanced"):
            self.settings.set("ocr_profile", selected_key)
            return

        was_running = self.is_running
        was_paused = self.is_paused

        if was_running:
            self.on_stop_work()

        try:
            old_engine = self.ocr_engine
            config.OCR_PROFILE = selected_key
            self.settings.set("ocr_profile", selected_key)

            self.ocr_engine = OCREngine()
            try:
                old_engine.cleanup()
            except Exception:
                pass

            log(f"✅ OCR профиль применён: {selected_label}", level="INFO")
            self.status_label.config(text=f"🟢 Профиль OCR: {selected_label}", foreground="green")

            if was_running:
                self.on_start_work()
                if was_paused and self.is_running and not self.is_paused:
                    self.on_pause()
        except Exception as e:
            log(f"❌ Ошибка применения OCR профиля: {e}", level="ERROR")
            messagebox.showerror("Ошибка", f"Не удалось применить профиль OCR: {e}")

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

    def _screenshot_loop(self):
        log("📸 Screenshot loop запущен", level="DEBUG")
        roi = self.roi_config.get()

        capture_source = str(getattr(config, "CAPTURE_SOURCE", "mss")).strip().lower()
        if capture_source not in {"mss", "obs_virtual_camera"}:
            log(
                f"⚠️ Неизвестный CAPTURE_SOURCE='{capture_source}', используем mss",
                level="WARNING",
            )
            capture_source = "mss"

        use_obs_capture = capture_source == "obs_virtual_camera"
        obs_capture = None
        if use_obs_capture:
            if self._cv2 is None:
                log(
                    "⚠️ CAPTURE_SOURCE=obs_virtual_camera, но cv2 недоступен. Fallback на mss.",
                    level="WARNING",
                )
                use_obs_capture = False
            else:
                camera_index = int(getattr(config, "OBS_CAMERA_INDEX", 0))
                api_preference = self._cv2.CAP_DSHOW if hasattr(self._cv2, "CAP_DSHOW") else 0
                obs_capture = (
                    self._cv2.VideoCapture(camera_index, api_preference)
                    if api_preference
                    else self._cv2.VideoCapture(camera_index)
                )

                if not obs_capture or not obs_capture.isOpened():
                    if obs_capture:
                        obs_capture.release()
                    obs_capture = None
                    log(
                        f"⚠️ OBS virtual camera index={camera_index} недоступна. Fallback на mss.",
                        level="WARNING",
                    )
                    use_obs_capture = False
                else:
                    target_w = int(getattr(config, "OBS_FRAME_WIDTH", 1920))
                    target_h = int(getattr(config, "OBS_FRAME_HEIGHT", 1080))
                    obs_capture.set(self._cv2.CAP_PROP_FRAME_WIDTH, target_w)
                    obs_capture.set(self._cv2.CAP_PROP_FRAME_HEIGHT, target_h)
                    log(
                        f"📷 Захват через OBS virtual camera (index={camera_index})",
                        level="INFO",
                    )

        if not use_obs_capture:
            log("🖥️ Захват через mss", level="INFO")

        interval = float(getattr(config, "SCREENSHOT_INTERVAL", 0.05))

        adaptive_enabled = bool(getattr(config, "ADAPTIVE_CAPTURE_ENABLED", True))
        min_interval = float(getattr(config, "SCREENSHOT_INTERVAL_MIN", 0.02))
        max_interval = float(getattr(config, "SCREENSHOT_INTERVAL_MAX", 0.14))
        step_up = float(getattr(config, "SCREENSHOT_INTERVAL_STEP_UP", 0.01))
        step_down = float(getattr(config, "SCREENSHOT_INTERVAL_STEP_DOWN", 0.005))
        target_q = int(getattr(config, "SCREENSHOT_QUEUE_TARGET", 1))
        high_watermark = int(getattr(config, "SCREENSHOT_QUEUE_HIGH_WATERMARK", 2))
        base_interval = float(getattr(config, "SCREENSHOT_INTERVAL", 0.05))
        keep_latest_only = bool(getattr(config, "OCR_KEEP_ONLY_LATEST_FRAME", True))

        last_tune_log = 0.0
        last_health_log = 0.0
        captured_frames = 0

        sct_context = mss.mss() if not use_obs_capture else nullcontext(None)
        try:
            with sct_context as sct:
                while ThreadLifecycle.is_ocr_running():
                    try:
                        if ThreadLifecycle.is_paused:
                            time.sleep(0.1)
                            continue

                        require_roi = (not use_obs_capture) or bool(getattr(config, "OBS_USE_ROI", False))
                        if require_roi and not roi:
                            time.sleep(0.2)
                            continue

                        queue_size = Queues.ocr_queue.qsize()
                        if queue_size >= high_watermark:
                            if adaptive_enabled:
                                interval = min(max_interval, interval + step_up)
                            time.sleep(interval)
                            continue

                        started = time.perf_counter()

                        if use_obs_capture and obs_capture is not None:
                            ok, bgr_frame = obs_capture.read()
                            if not ok or bgr_frame is None:
                                time.sleep(interval)
                                continue

                            frame = self._cv2.cvtColor(bgr_frame, self._cv2.COLOR_BGR2RGB)

                            if bool(getattr(config, "OBS_USE_ROI", False)) and roi:
                                x, y, w, h = roi
                                fh, fw = frame.shape[:2]
                                x0 = max(0, min(int(x), fw - 1))
                                y0 = max(0, min(int(y), fh - 1))
                                x1 = max(x0 + 1, min(int(x + w), fw))
                                y1 = max(y0 + 1, min(int(y + h), fh))
                                frame = frame[y0:y1, x0:x1]

                            frame = self._auto_crop_subtitle_band(frame)
                        else:
                            x, y, w, h = roi
                            monitor = {"top": y, "left": x, "width": w, "height": h}
                            screenshot = sct.grab(monitor)
                            frame = np.frombuffer(screenshot.rgb, dtype=np.uint8)
                            frame = frame.reshape(screenshot.height, screenshot.width, 3)
                            frame = self._auto_crop_subtitle_band(frame)

                        if keep_latest_only:
                            # Low-latency режим: OCR всегда видит только самый свежий кадр.
                            while not Queues.ocr_queue.empty():
                                try:
                                    Queues.ocr_queue.get_nowait()
                                except Empty:
                                    break

                            try:
                                Queues.ocr_queue.put_nowait(frame)
                            except Full:
                                try:
                                    Queues.ocr_queue.get_nowait()
                                except Empty:
                                    pass
                                try:
                                    Queues.ocr_queue.put_nowait(frame)
                                except Full:
                                    pass
                        else:
                            Queues.ocr_queue.put(frame)

                        captured_frames += 1

                        elapsed = time.perf_counter() - started
                        queue_size = Queues.ocr_queue.qsize()
                        now = time.time()

                        health_interval = float(getattr(config, "CAPTURE_HEALTH_LOG_INTERVAL_SEC", 5.0))
                        if now - last_health_log >= health_interval:
                            frame_shape = getattr(frame, "shape", None)
                            log(
                                f"📸 Захват активен: frames={captured_frames} q={queue_size} interval={interval:.3f}s roi={roi} frame={frame_shape}",
                                level="INFO",
                            )
                            last_health_log = now

                        if adaptive_enabled:
                            if queue_size > target_q:
                                interval = min(max_interval, interval + step_up)
                            elif queue_size == 0 and elapsed < (interval * 0.6):
                                interval = max(min_interval, interval - step_down)
                            elif interval > base_interval:
                                interval = max(base_interval, interval - (step_down * 0.5))

                            if config.DEBUG_MODE and now - last_tune_log > 5.0:
                                log(
                                    f"⚡ Capture interval={interval:.3f}s q={queue_size} elapsed={elapsed:.3f}s",
                                    level="DEBUG",
                                )
                                last_tune_log = now

                        time.sleep(interval)

                    except Exception as e:
                        log(f"❌ Ошибка захвата: {e}", level="ERROR")
        finally:
            if obs_capture is not None:
                try:
                    obs_capture.release()
                except Exception:
                    pass

        log("⏹️ Screenshot loop завершён", level="DEBUG")

    def on_select_roi(self):
        log("🖱️ Выбор региона...", level="INFO")

        with mss.mss() as sct:
            screenshot = sct.grab(sct.monitors[1])
            pil_image = PILImage.frombytes("RGB", screenshot.size, screenshot.rgb)

        selection = tk.Toplevel(self.root)
        selection.title("Выделите область субтитров")
        selection.attributes("-fullscreen", True)
        selection.attributes("-topmost", True)

        canvas = tk.Canvas(selection, width=pil_image.width, height=pil_image.height, highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        photo = ImageTk.PhotoImage(pil_image)
        canvas.image = photo
        canvas.create_image(0, 0, image=photo, anchor=tk.NW)

        roi_data = {"start": None, "rect": None}

        def on_press(event):
            roi_data["start"] = (event.x, event.y)
            if roi_data["rect"] is not None:
                canvas.delete(roi_data["rect"])
                roi_data["rect"] = None

        def on_drag(event):
            if not roi_data["start"]:
                return
            x1, y1 = roi_data["start"]
            if roi_data["rect"] is not None:
                canvas.delete(roi_data["rect"])
            roi_data["rect"] = canvas.create_rectangle(x1, y1, event.x, event.y, outline="lime", width=2)

        def on_release(event):
            if not roi_data["start"]:
                return
            x1, y1 = roi_data["start"]
            x2, y2 = event.x, event.y
            x = min(x1, x2)
            y = min(y1, y2)
            w = abs(x2 - x1)
            h = abs(y2 - y1)
            if w < 10 or h < 10:
                return

            roi = (x, y, w, h)
            self.roi_config.save(roi)
            self.label_roi_status.config(text=f"ROI: ({x}, {y}) {w}x{h}", foreground="green")
            selection.destroy()

        def on_key(event):
            if event.keysym == "Escape":
                selection.destroy()

        canvas.bind("<Button-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        selection.bind("<Key>", on_key)
        selection.focus_set()
        selection.wait_window()

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
        if self.is_running and not messagebox.askyesno("Подтверждение", "Остановить захват и выйти?"):
            return

        try:
            self.on_stop_work()
        finally:
            try:
                self.audio_player.cleanup()
            except Exception:
                pass
            try:
                self.ocr_engine.cleanup()
            except Exception:
                pass
            self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = MainWindow()
    app.run()
