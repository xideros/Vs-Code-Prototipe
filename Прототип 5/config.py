# config.py — Централизованная конфигурация приложения

import os

# ============================================================================
# ПУТИ И ФАЙЛЫ
# ============================================================================
APP_NAME = "Game Subtitle Assistant - Log Pipeline Prototype 5"
APP_VERSION = "1.0.0"
CONFIG_DIR = os.path.expanduser("~/.game_subtitle_assistant_proto5")
HISTORY_FILE = os.path.join(CONFIG_DIR, "history.txt")
CACHE_DIR = os.path.join(CONFIG_DIR, "audio_cache")
PHRASES_FILE = os.path.join(CONFIG_DIR, "game_phrases.txt")
UE_EXTRACTOR_OUTPUT_DIR = os.path.join(CONFIG_DIR, "extracted_resources")
UNREAL_LOCRES_TOOL = r"C:\Users\Asus\Desktop\Новая папка\UnrealLocres.exe"

# Создаём директории если их нет
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(UE_EXTRACTOR_OUTPUT_DIR, exist_ok=True)

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

GAME_ROOT = ""
GAME_AUTODETECT_ENABLED = True
GAME_AUTODETECT_POLL_INTERVAL_MS = 1500
AUTO_SCAN_ON_GAME_DETECT = True
AUTO_IMPORT_BEST_CANDIDATE = True
AUTO_SCAN_RESULT_LIMIT = 300
GAME_AUTODETECT_EXCLUDED_EXE_NAMES = {
    "python.exe",
    "pythonw.exe",
    "code.exe",
    "explorer.exe",
    "powershell.exe",
    "pwsh.exe",
    "cmd.exe",
    "windowsterminal.exe",
}
IMPORT_SUBTITLE_LINE_DELAY = 0.20
UE_EXTRACTOR_TOOL = r"C:\Users\Asus\Desktop\repak_cli-x86_64-pc-windows-msvc\repak.exe"
UE_EXTRACTOR_COMMAND_TEMPLATE = 'cmd /c ""{tool}" get "{container}" "{internal_path}" > "{expected_output_path}""'

# Настройки сканера возможных источников субтитров.
SCAN_MAX_FILES = 100000
SCAN_RESULT_LIMIT = 50
TEXT_COMPARISON_QUEUE_MAXSIZE = 1
TEXT_COMPARISON_KEEP_LATEST = True

# ============================================================================
# THREADING КОНФИГУРАЦИЯ
# ============================================================================
THREAD_POOL_MAX_WORKERS = 2  # Макс потоков для TTS синтеза
TTS_SINGLE_FLIGHT = True
TTS_WORKER_TIMEOUT = 0.5  # Таймаут для очередей (сек)
COMPARISON_QUEUE_TIMEOUT = 0.5
PLAYBACK_QUEUE_TIMEOUT = 0.5
THREAD_STOP_JOIN_TIMEOUT = 4.0

# ============================================================================
# ТЕКСТОВАЯ ОБРАБОТКА
# ============================================================================
DUPLICATE_SKIP_TIMEOUT = 1.2  # Пропускаем одинаковый текст за N секунд
TEXT_PREVIEW_LENGTH = 50  # Длина превью текста в логах
TEXT_NORMALIZATION_SPACES = True  # Нормализовать пробелы
TEXT_SIMILARITY_THRESHOLD = 0.92
TEXT_MIN_COMPARE_LEN = 7
TEXT_CONFIRM_FRAMES = 2
TEXT_CONFIRM_MIN_CANONICAL_LEN = 4
TEXT_MIN_LETTERS = 4
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
WINDOW_WIDTH = 520
WINDOW_HEIGHT = 430
WINDOW_RESIZABLE = True
WINDOW_TOPMOST = False  # Окно поверх других

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
