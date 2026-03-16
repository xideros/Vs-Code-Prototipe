# ui/__init__.py - Главное окно приложения

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from PIL import Image as PILImage

import config
from core import OCREngine, TTSEngine, TextTranslator, AudioPlayer
from storage import (
    HistoryManager, AudioCache, ROIConfig
)
from utils.logger import log
import tempfile
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import mss
from PIL import Image as PILImage
from PIL import ImageTk

import config
from core import AudioPlayer, OCREngine, TTSEngine, TextTranslator
from storage import AudioCache, HistoryManager, ROIConfig
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
        self.root.title(config.WINDOW_TITLE)
        self.root.resizable(False, False)
        self.root.minsize(config.WINDOW_WIDTH, config.WINDOW_HEIGHT)

        # Бизнес-компоненты
        self.ocr_engine = OCREngine()
        self.tts_engine = TTSEngine()
        self.translator = TextTranslator()
        self.audio_player = AudioPlayer()
        self.audio_cache = AudioCache()
        self.history = HistoryManager()
        self.roi_config = ROIConfig()

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

        self._build_ui()
        self._apply_initial_geometry()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        log("✅ MainWindow инициализирована успешно", level="INFO")

    def _build_ui(self):
        container = ttk.Frame(self.root, padding=10)
        container.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        title = ttk.Label(
            container,
            text="Game Subtitle Assistant",
            font=("Segoe UI", 12, "bold"),
        )
        title.grid(row=0, column=0, sticky=tk.W, pady=(0, 8))

        controls = ttk.LabelFrame(container, text="Управление", padding=8)
        controls.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 8))

        self.btn_start = ttk.Button(controls, text="▶ Начать", command=self.on_start_work, width=11)
        self.btn_stop = ttk.Button(
            controls,
            text="■ Стоп",
            command=self.on_stop_work,
            width=11,
            state=tk.DISABLED,
        )
        self.btn_pause = ttk.Button(
            controls,
            text="⏸ Пауза",
            command=self.on_pause,
            width=11,
            state=tk.DISABLED,
        )

        self.btn_start.grid(row=0, column=0, padx=3, pady=3)
        self.btn_stop.grid(row=0, column=1, padx=3, pady=3)
        self.btn_pause.grid(row=0, column=2, padx=3, pady=3)

        roi_box = ttk.LabelFrame(container, text="Регион субтитров", padding=8)
        roi_box.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 8))

        self.btn_select_roi = ttk.Button(roi_box, text="🖱 Выбрать регион", command=self.on_select_roi, width=18)
        self.btn_select_roi.grid(row=0, column=0, padx=(0, 8), pady=3)

        self.label_roi_status = ttk.Label(roi_box, text="ROI не выбран", foreground="red")
        self.label_roi_status.grid(row=0, column=1, sticky=tk.W)

        tools = ttk.Frame(container)
        tools.grid(row=3, column=0, sticky=tk.W, pady=(0, 8))
        ttk.Button(tools, text="Очистить кеш", command=self.on_clear_cache, width=12).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(tools, text="Логи", command=self.on_show_logs, width=12).grid(row=0, column=1, padx=4)

        status_box = ttk.LabelFrame(container, text="Статус", padding=8)
        status_box.grid(row=4, column=0, sticky=(tk.W, tk.E))
        self.status_label = ttk.Label(status_box, text="🟢 Готово", foreground="green", font=("Segoe UI", 10, "bold"))
        self.status_label.grid(row=0, column=0, sticky=tk.W)

        roi = self.roi_config.get()
        if roi:
            self.label_roi_status.config(
                text=f"ROI: ({roi[0]}, {roi[1]}) {roi[2]}x{roi[3]}",
                foreground="green",
            )

    def _apply_initial_geometry(self):
        self.root.update_idletasks()
        width = config.WINDOW_WIDTH
        height = config.WINDOW_HEIGHT
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
            self.text_comp_worker = TextComparisonWorker(self.audio_player)
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

            for t in self.threads:
                t.join(timeout=0.5)
            self.threads.clear()

            Queues.clear_all()
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
            self.audio_player.pause()
            self.btn_pause.config(text="▶ Продолжить")
            self.status_label.config(text="⏸ Пауза", foreground="orange")
        else:
            ThreadLifecycle.unpause()
            self.audio_player.unpause()
            self.btn_pause.config(text="⏸ Пауза")
            self.status_label.config(text="🔴 Захват активен", foreground="red")
            log("▶️ Захват продолжен", level="INFO")

    def _screenshot_loop(self):
        log("📸 Screenshot loop запущен", level="DEBUG")
        roi = self.roi_config.get()

        while ThreadLifecycle.is_ocr_running():
            try:
                if not roi:
                    time.sleep(0.2)
                    continue

                if Queues.ocr_queue.qsize() >= 2:
                    time.sleep(0.05)
                    continue

                x, y, w, h = roi
                monitor = {"top": y, "left": x, "width": w, "height": h}

                with mss.mss() as sct:
                    screenshot = sct.grab(monitor)
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="screenshot_") as f:
                        temp_path = f.name
                    pil_image = PILImage.frombytes("RGB", screenshot.size, screenshot.rgb)
                    pil_image.save(temp_path)

                Queues.ocr_queue.put(temp_path)
                time.sleep(config.SCREENSHOT_INTERVAL)

            except Exception as e:
                log(f"❌ Ошибка захвата: {e}", level="ERROR")

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
