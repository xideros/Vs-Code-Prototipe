# config.py — Централизованная конфигурация приложения

import os

# ============================================================================
# ПУТИ И ФАЙЛЫ
# ============================================================================
APP_NAME = "Game Subtitle Assistant"
APP_VERSION = "1.0.0"
CONFIG_DIR = os.path.expanduser("~/.game_subtitle_assistant")
CONFIG_FILE = os.path.join(CONFIG_DIR, "roi_config.txt")
HISTORY_FILE = os.path.join(CONFIG_DIR, "history.txt")
CACHE_DIR = os.path.join(CONFIG_DIR, "audio_cache")
PHRASES_FILE = os.path.join(CONFIG_DIR, "game_phrases.txt")

# Создаём директории если их нет
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# ============================================================================
# OCR КОНФИГУРАЦИЯ
# ============================================================================
USE_TESSERACT = True  # True = Tesseract, False = EasyOCR
TESSERACT_PATHS = [
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
]
OCR_LANGUAGES = ['rus+eng']
EASYOCR_LANGUAGES = ['en', 'ru']
EASYOCR_USE_GPU = True

# ============================================================================
# ПЕРЕВОД КОНФИГУРАЦИЯ
# ============================================================================
TRANSLATOR_SOURCE_LANG = "auto"  # Автоопределение
TRANSLATOR_TARGET_LANG = "ru"
TRANSLATION_CACHE_SIZE = 10000  # Макс элементов в кеше

# ============================================================================
# TTS КОНФИГУРАЦИЯ (Edge TTS)
# ============================================================================
TTS_VOICE = "ru-RU-DmitryNeural"  # Русский мужской голос
TTS_SPEED_MIN = 1.0
TTS_SPEED_MAX = 3.0
TTS_SPEED_DEFAULT = 1.0  # В UI это будет ползунок 0-30 (делим на 10)

# ============================================================================
# АУДИО КОНФИГУРАЦИЯ (pygame.mixer)
# ============================================================================
AUDIO_VOLUME_MIN = 0
AUDIO_VOLUME_MAX = 100
AUDIO_VOLUME_DEFAULT = 70
AUDIO_SAMPLERATE = 44100
AUDIO_CHANNELS = 2

# ============================================================================
# СКРИНШОТ КОНФИГУРАЦИЯ (mss)
# ============================================================================
SCREENSHOT_INTERVAL = 0.05  # Интервал между скриншотами (сек)
SCREENSHOT_FORMAT = "png"
SCREENSHOT_TEMP_FILE = "screenshot.png"

# ============================================================================
# THREADING КОНФИГУРАЦИЯ
# ============================================================================
THREAD_POOL_MAX_WORKERS = 10  # Макс потоков для TTS синтеза
TTS_WORKER_TIMEOUT = 0.5  # Таймаут для очередей (сек)
OCR_QUEUE_TIMEOUT = 0.5
COMPARISON_QUEUE_TIMEOUT = 0.5
PLAYBACK_QUEUE_TIMEOUT = 0.5

# ============================================================================
# ТЕКСТОВАЯ ОБРАБОТКА
# ============================================================================
DUPLICATE_SKIP_TIMEOUT = 3.0  # Пропускаем одинаковый текст за N секунд
TEXT_PREVIEW_LENGTH = 50  # Длина превью текста в логах
TEXT_NORMALIZATION_SPACES = True  # Нормализовать пробелы

# ============================================================================
# ДЕБАГ ЛОГИРОВАНИЕ
# ============================================================================
DEBUG_MODE = False
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
LOG_TO_FILE = True
LOG_FILE = os.path.join(CONFIG_DIR, "app.log")

# ============================================================================
# UI КОНФИГУРАЦИЯ (Tkinter)
# ============================================================================
WINDOW_TITLE = f"{APP_NAME} v{APP_VERSION}"
WINDOW_WIDTH = 460
WINDOW_HEIGHT = 360
WINDOW_RESIZABLE = True
WINDOW_TOPMOST = False  # Окно поверх других

# ROI SELECTOR НАСТРОЙКИ
ROI_SELECTOR_TITLE = "Выберите область для захвата текста"
ROI_SELECTOR_WIDTH = 1920
ROI_SELECTOR_HEIGHT = 1080

# ============================================================================
# SYSTEM TRAY КОНФИГУРАЦИЯ
# ============================================================================
TRAY_MENU_SHOW = "Показать"
TRAY_MENU_HIDE = "Скрыть"
TRAY_MENU_EXIT = "Выход"

# ============================================================================
# ЦВЕТА И СТИЛИ
# ============================================================================
COLOR_SUCCESS = "#90EE90"  # Зелёный
COLOR_ERROR = "#FF6B6B"    # Красный
COLOR_WARNING = "#FFD93D"  # Жёлтый
COLOR_INFO = "#6BCB77"     # Голубой-зелёный

FONT_DEFAULT = ("Arial", 11)
FONT_BUTTON = ("Arial", 11, "bold")
FONT_STATUS = ("Arial", 10)

# ============================================================================
# СИСТЕМНЫЕ ПАРАМЕТРЫ
# ============================================================================
PLATFORM = __import__('sys').platform
IS_WINDOWS = PLATFORM == 'win32'
IS_LINUX = PLATFORM.startswith('linux')
IS_MAC = PLATFORM == 'darwin'
