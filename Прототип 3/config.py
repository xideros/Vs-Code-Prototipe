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
TESSERACT_OEM = 3
TESSERACT_PSM = 6
TESSERACT_PSM_CANDIDATES = [6, 7, 11]
TESSERACT_MIN_CONF = 20

# Прототип 3: новый конфиг OCR-стека
# OCR_BACKEND: auto | tesseract | easyocr | paddleocr
OCR_BACKEND = "auto"
# OCR_PROFILE: realtime | balanced | quality
OCR_PROFILE = "realtime"
# При auto выбираем первый доступный backend из списка
OCR_BACKEND_PRIORITY = ["tesseract", "easyocr", "paddleocr"]

# Профили OCR-пайплайна: влияние на предобработку и постфильтрацию.
OCR_PROFILE_PRESETS = {
    "realtime": {
        "preprocess": False,
        "upscale": 1.0,
        "threshold": "none",   # none | otsu | adaptive
        "denoise": False,
        "normalize_spaces": True,
        "merge_hyphen_wrap": True,
        "min_chars": 2,
        "min_alpha_ratio": 0.20,
    },
    "balanced": {
        "preprocess": True,
        "upscale": 1.2,
        "threshold": "otsu",
        "denoise": True,
        "clahe": True,
        "sharpen": False,
        "normalize_spaces": True,
        "merge_hyphen_wrap": True,
        "min_chars": 2,
        "min_alpha_ratio": 0.16,
    },
    "quality": {
        "preprocess": True,
        "upscale": 1.5,
        "threshold": "adaptive",
        "denoise": True,
        "clahe": True,
        "sharpen": False,
        "normalize_spaces": True,
        "merge_hyphen_wrap": True,
        "min_chars": 2,
        "min_alpha_ratio": 0.16,
    },
}

# ============================================================================
# ПЕРЕВОД КОНФИГУРАЦИЯ
# ============================================================================
TRANSLATOR_SOURCE_LANG = "auto"  # Автоопределение
TRANSLATOR_TARGET_LANG = "ru"
TRANSLATION_CACHE_SIZE = 10000  # Макс элементов в кеше

# Доступные языки для UI (код -> подпись)
LANGUAGE_OPTIONS = [
    ("auto", "Авто"),
    ("ru", "Русский"),
    ("en", "Английский"),
    ("de", "Немецкий"),
    ("fr", "Французский"),
    ("es", "Испанский"),
    ("it", "Итальянский"),
    ("pt", "Португальский"),
    ("tr", "Турецкий"),
    ("ja", "Японский"),
    ("ko", "Корейский"),
    ("zh-CN", "Китайский (упр.)"),
]

DEFAULT_READ_LANGUAGE = "auto"
DEFAULT_SPEECH_LANGUAGE = "ru"

# Коды для deep_translator
TRANSLATOR_LANGUAGE_MAP = {
    "auto": "auto",
    "ru": "russian",
    "en": "english",
    "de": "german",
    "fr": "french",
    "es": "spanish",
    "it": "italian",
    "pt": "portuguese",
    "tr": "turkish",
    "ja": "japanese",
    "ko": "korean",
    "zh-CN": "chinese (simplified)",
}

# ============================================================================
# TTS КОНФИГУРАЦИЯ (Edge TTS)
# ============================================================================
TTS_VOICE = "ru-RU-DmitryNeural"  # Русский мужской голос
TTS_VOICE_BY_LANGUAGE = {
    "ru": "ru-RU-DmitryNeural",
    "en": "en-US-GuyNeural",
    "de": "de-DE-ConradNeural",
    "fr": "fr-FR-HenriNeural",
    "es": "es-ES-AlvaroNeural",
    "it": "it-IT-DiegoNeural",
    "pt": "pt-BR-AntonioNeural",
    "tr": "tr-TR-AhmetNeural",
    "ja": "ja-JP-KeitaNeural",
    "ko": "ko-KR-InJoonNeural",
    "zh-CN": "zh-CN-YunxiNeural",
}
TTS_VOICE_OPTIONS = {
    "ru": [
        ("ru-RU-DmitryNeural", "Русский мужской (Dmitry)"),
        ("ru-RU-SvetlanaNeural", "Русский женский (Svetlana)"),
    ],
    "en": [
        ("en-US-GuyNeural", "English male (Guy)"),
        ("en-US-JennyNeural", "English female (Jenny)"),
    ],
    "de": [
        ("de-DE-ConradNeural", "Deutsch mannlich (Conrad)"),
        ("de-DE-KatjaNeural", "Deutsch weiblich (Katja)"),
    ],
    "fr": [
        ("fr-FR-HenriNeural", "Francais homme (Henri)"),
        ("fr-FR-DeniseNeural", "Francais femme (Denise)"),
    ],
    "es": [
        ("es-ES-AlvaroNeural", "Espanol hombre (Alvaro)"),
        ("es-ES-ElviraNeural", "Espanol mujer (Elvira)"),
    ],
    "it": [
        ("it-IT-DiegoNeural", "Italiano uomo (Diego)"),
        ("it-IT-ElsaNeural", "Italiano donna (Elsa)"),
    ],
    "pt": [
        ("pt-BR-AntonioNeural", "Portugues homem (Antonio)"),
        ("pt-BR-FranciscaNeural", "Portugues mulher (Francisca)"),
    ],
    "tr": [
        ("tr-TR-AhmetNeural", "Turkce erkek (Ahmet)"),
        ("tr-TR-EmelNeural", "Turkce kadin (Emel)"),
    ],
    "ja": [
        ("ja-JP-KeitaNeural", "Japanese male (Keita)"),
        ("ja-JP-NanamiNeural", "Japanese female (Nanami)"),
    ],
    "ko": [
        ("ko-KR-InJoonNeural", "Korean male (InJoon)"),
        ("ko-KR-SunHiNeural", "Korean female (SunHi)"),
    ],
    "zh-CN": [
        ("zh-CN-YunxiNeural", "Chinese male (Yunxi)"),
        ("zh-CN-XiaoxiaoNeural", "Chinese female (Xiaoxiao)"),
    ],
}
TTS_SPEED_MIN = 1.0
TTS_SPEED_MAX = 3.0
TTS_SPEED_DEFAULT = 1.0  # В UI это будет ползунок 0-30 (делим на 10)
TTS_SYNTH_TIMEOUT_SEC = 3.2
TTS_MAX_TEXT_CHARS = 120
TTS_MIN_ALPHA_RATIO = 0.30
TTS_DROP_IF_OLDER_THAN_SEC = 2.5
PLAYBACK_DROP_IF_OLDER_THAN_SEC = 3.2

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
CAPTURE_SOURCE = "obs_virtual_camera"  # mss | obs_virtual_camera
OBS_CAMERA_INDEX = 0
OBS_FRAME_WIDTH = 1920
OBS_FRAME_HEIGHT = 1080
OBS_USE_ROI = False

SCREENSHOT_INTERVAL = 0.05  # Интервал между скриншотами (сек)
ADAPTIVE_CAPTURE_ENABLED = True
SCREENSHOT_INTERVAL_MIN = 0.02
SCREENSHOT_INTERVAL_MAX = 0.14
SCREENSHOT_INTERVAL_STEP_UP = 0.01
SCREENSHOT_INTERVAL_STEP_DOWN = 0.005
SCREENSHOT_QUEUE_TARGET = 1
SCREENSHOT_QUEUE_HIGH_WATERMARK = 1
OCR_QUEUE_MAXSIZE = 1
OCR_KEEP_ONLY_LATEST_FRAME = True
TEXT_COMPARISON_QUEUE_MAXSIZE = 1
TEXT_COMPARISON_KEEP_LATEST = True
AUTO_SUBTITLE_DETECT_ENABLED = True
AUTO_SUBTITLE_SCAN_TOP_RATIO = 0.40
AUTO_SUBTITLE_SCAN_BOTTOM_RATIO = 0.98
AUTO_SUBTITLE_BAND_HEIGHT_RATIO = 0.22
AUTO_SUBTITLE_SIDE_MARGIN_RATIO = 0.06
AUTO_SUBTITLE_REDETECT_EVERY = 10
AUTO_SUBTITLE_SMOOTHING = 0.60
AUTO_SUBTITLE_WARMUP_FRAMES = 20
AUTO_SUBTITLE_MIN_EDGE_DENSITY = 0.012
AUTO_SUBTITLE_MAX_JUMP_RATIO = 0.18
SCREENSHOT_FORMAT = "png"
SCREENSHOT_TEMP_FILE = "screenshot.png"

# ============================================================================
# THREADING КОНФИГУРАЦИЯ
# ============================================================================
THREAD_POOL_MAX_WORKERS = 2  # Макс потоков для TTS синтеза
TTS_SINGLE_FLIGHT = True
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
TEXT_SIMILARITY_THRESHOLD = 0.84
TEXT_MIN_COMPARE_LEN = 10
TEXT_CONFIRM_FRAMES = 1
TEXT_CONFIRM_MIN_CANONICAL_LEN = 6
TEXT_MIN_LETTERS = 8
TEXT_MIN_WORDS = 2
TEXT_SINGLE_WORD_MIN_LEN = 12
TEXT_RU_ONLY_MODE_MIN_CYR_RATIO = 0.72
TEXT_SAME_LANG_SCRIPT_RATIO_THRESHOLDS = {
    "ru": 0.72,
    "en": 0.75,
    "de": 0.75,
    "fr": 0.75,
    "es": 0.75,
    "it": 0.75,
    "pt": 0.75,
    "tr": 0.75,
    "ja": 0.70,
    "ko": 0.75,
    "zh-CN": 0.70,
}
TRANSLATE_ONLY_CONFIRMED_TEXT = True

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
WINDOW_WIDTH = 560
WINDOW_HEIGHT = 500
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
