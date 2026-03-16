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
        self._translator = None
        self._detect = None
        try:
            from langdetect import detect
            self._detect = detect
        except Exception as e:
            log(f"⚠️ langdetect недоступен: {e}", level="WARNING")
        self._rebuild_translator()
        log(f"✅ Переводчик инициализирован: {self.source_lang} → {self.target_lang}", level="INFO")

    def _map_lang(self, lang_code: str) -> str:
        """Преобразует код UI в формат deep_translator."""
        mapping = getattr(config, "TRANSLATOR_LANGUAGE_MAP", {})
        return mapping.get(lang_code, lang_code)

    def _rebuild_translator(self):
        """Пересоздать объект переводчика для новых языков."""
        source = self._map_lang(self.source_lang)
        target = self._map_lang(self.target_lang)
        self._translator = GoogleTranslator(
            source_language=source,
            target_language=target,
        )

    def set_languages(self, source_lang: str, target_lang: str):
        """Сменить языки перевода на лету."""
        source_lang = (source_lang or "auto").strip()
        target_lang = (target_lang or "ru").strip()
        if self.source_lang == source_lang and self.target_lang == target_lang:
            return

        self.source_lang = source_lang
        self.target_lang = target_lang
        self._rebuild_translator()
        self.clear_cache()
        log(f"🌐 Языки перевода обновлены: {self.source_lang} → {self.target_lang}", level="INFO")
    
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

        # Если язык чтения и озвучки одинаковый, перевод не нужен.
        if self.source_lang != "auto" and self.source_lang == self.target_lang:
            return text
        
        # Быстрый путь: если есть кириллица, считаем текст русским и не переводим.
        if any(('а' <= ch.lower() <= 'я') or ch in ('ё', 'Ё') for ch in text):
            return text

        # Пробуем определить язык
        detected_lang = None
        try:
            if self._detect is not None:
                detected_lang = self._detect(text)
                log(f"🌐 Определён язык: {detected_lang}", level="DEBUG")
            else:
                detected_lang = 'en'
        except Exception as e:
            log(f"⚠️ Ошибка определения языка: {e}, предполагаем английский", level="WARNING")
            detected_lang = 'en'
        
        # Если текст уже на русском - не переводим
        if detected_lang == self.target_lang:
            log(f"✅ Текст уже на целевом языке: {text[:30]}", level="DEBUG")
            return text
        
        # Проверяем кеш
        if text in self.cache:
            log(f"💾 Перевод из кеша: {text[:40]}", level="DEBUG")
            return self.cache[text]
        
        try:
            translated = self._translator.translate(text)
            
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
