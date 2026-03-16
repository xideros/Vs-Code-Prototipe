# storage/settings.py - Пользовательские настройки (громкость, скорость)

import json
import os
import config
from utils.logger import log

class SettingsManager:
    """Управление пользовательскими настройками"""
    
    DEFAULT_SETTINGS = {
        'volume': config.AUDIO_VOLUME_DEFAULT,
        'speed': int(config.TTS_SPEED_DEFAULT * 10),  # В UI шкала 0-30
        'window_width': config.WINDOW_WIDTH,
        'window_height': config.WINDOW_HEIGHT,
        'ocr_engine': 'tesseract' if config.USE_TESSERACT else 'easyocr',
        'ocr_profile': getattr(config, 'OCR_PROFILE', 'balanced'),
        'read_language': getattr(config, 'DEFAULT_READ_LANGUAGE', 'auto'),
        'speech_language': getattr(config, 'DEFAULT_SPEECH_LANGUAGE', 'ru'),
        'tts_voice': getattr(config, 'TTS_VOICE', 'ru-RU-DmitryNeural'),
    }
    
    def __init__(self):
        self.settings_file = os.path.join(config.CONFIG_DIR, 'settings.json')
        self.settings = self.DEFAULT_SETTINGS.copy()
        self.load()
    
    def load(self):
        """Загрузить настройки из файла"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # Обновляем с загруженными, но сохраняем дефолты для новых ключей
                    self.settings.update(loaded)
                    log(f"⚙️ Настройки загружены", level="INFO")
        except Exception as e:
            log(f"⚠️ Ошибка загрузки настроек: {e}, используются дефолты", level="WARNING")
            self.settings = self.DEFAULT_SETTINGS.copy()
    
    def save(self):
        """Сохранить настройки в файл"""
        try:
            os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            log(f"💾 Настройки сохранены", level="DEBUG")
        except Exception as e:
            log(f"❌ Ошибка сохранения настроек: {e}", level="ERROR")
    
    def get(self, key: str, default=None):
        """Получить значение настройки"""
        return self.settings.get(key, default or self.DEFAULT_SETTINGS.get(key))
    
    def set(self, key: str, value):
        """Установить значение настройки"""
        self.settings[key] = value
        self.save()
    
    def get_all(self) -> dict:
        """Получить все настройки"""
        return self.settings.copy()
    
    def reset(self):
        """Сбросить на дефолты"""
        self.settings = self.DEFAULT_SETTINGS.copy()
        self.save()
        log("🔄 Настройки сброшены на дефолты", level="INFO")
