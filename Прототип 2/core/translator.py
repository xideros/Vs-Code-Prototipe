# core/translator.py - Перевод текста (GoogleTranslator + кеш)

from deep_translator import GoogleTranslator
import config
from utils.logger import log

class TextTranslator:
    """
    Единственный класс для перевода.
    Кеширует переводы для ускорения.
    """
    
    def __init__(self):
        """Инициализация переводчика"""
        self.cache = {}
        self.source_lang = config.TRANSLATOR_SOURCE_LANG
        self.target_lang = config.TRANSLATOR_TARGET_LANG
        log(f"✅ Переводчик инициализирован: {self.source_lang} → {self.target_lang}", level="INFO")
    
    def translate(self, text: str) -> str:
        """
        Перевести текст если он не на русском
        
        Args:
            text: Исходный текст
            
        Returns:
            Текст на русском языке
        """
        if not text or len(text) < 2:
            return ""
        
        # Пробуем определить язык
        detected_lang = None
        try:
            from langdetect import detect
            detected_lang = detect(text)
            log(f"🌐 Определён язык: {detected_lang}", level="DEBUG")
        except Exception as e:
            log(f"⚠️ Ошибка определения языка: {e}, предполагаем английский", level="WARNING")
            detected_lang = 'en'
        
        # Если текст уже на русском - не переводим
        if detected_lang == 'ru':
            log(f"✅ Текст уже на русском: {text[:30]}", level="DEBUG")
            return text
        
        # Проверяем кеш
        if text in self.cache:
            log(f"💾 Перевод из кеша: {text[:40]}", level="DEBUG")
            return self.cache[text]
        
        try:
            translator = GoogleTranslator(
                source_language=self.source_lang,
                target_language=self.target_lang
            )
            translated = translator.translate(text)
            
            # Сохраняем в кеш (с ограничением)
            if len(self.cache) < config.TRANSLATION_CACHE_SIZE:
                self.cache[text] = translated
            
            log(f"📝 Переведено: {text[:30]} → {translated[:30]}", level="DEBUG")
            return translated
            
        except Exception as e:
            log(f"❌ Ошибка перевода: {e}", level="ERROR")
            return text  # Возвращаем оригинал при ошибке
    
    def clear_cache(self):
        """Очистить кеш переводов"""
        self.cache.clear()
        log("🗑️ Кеш переводов очищен", level="INFO")
    
    def get_cache_size(self) -> int:
        """Получить размер кеша"""
        return len(self.cache)
