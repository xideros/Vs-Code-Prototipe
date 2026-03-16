# storage/cache.py - Кеш аудиофайлов (MD5 → MP3)

import os
import config
from utils.logger import log
from utils.helpers import get_md5_hash, get_cache_path, ensure_dir

class AudioCache:
    """Управление кешем аудиофайлов"""
    
    def __init__(self):
        self.cache_dir = config.CACHE_DIR
        ensure_dir(self.cache_dir)
        log(f"💾 AudioCache инициализирован: {self.cache_dir}", level="INFO")
    
    def get_path(self, text: str) -> str:
        """
        Получить путь кеша для текста
        
        Args:
            text: Исходный текст
            
        Returns:
            Путь к файлу в кеше
        """
        return get_cache_path(text)
    
    def exists(self, text: str) -> bool:
        """
        Проверить если аудио в кеше
        
        Args:
            text: Исходный текст
            
        Returns:
            True если файл существует
        """
        path = self.get_path(text)
        return os.path.exists(path)
    
    def get(self, text: str) -> str:
        """
        Получить аудио из кеша
        
        Args:
            text: Исходный текст
            
        Returns:
            Путь к файлу или "" если не в кеше
        """
        path = self.get_path(text)
        if os.path.exists(path):
            log(f"💾 Из кеша: {path[:30]}", level="DEBUG")
            return path
        return ""
    
    def put(self, text: str, audio_path: str):
        """
        Добавить аудио в кеш
        
        Args:
            text: Исходный текст
            audio_path: Путь к аудиофайлу
        """
        try:
            cache_path = self.get_path(text)
            if audio_path != cache_path:  # Если это не уже кешированный файл
                import shutil
                shutil.copy2(audio_path, cache_path)
                log(f"💾 В кеш: {cache_path[:30]}", level="DEBUG")
        except Exception as e:
            log(f"❌ Ошибка кеша: {e}", level="ERROR")
    
    def clear(self):
        """Очистить весь кеш"""
        try:
            import shutil
            if os.path.exists(self.cache_dir):
                shutil.rmtree(self.cache_dir)
            ensure_dir(self.cache_dir)
            log("🗑️ Кеш очищен", level="INFO")
        except Exception as e:
            log(f"❌ Ошибка очистки кеша: {e}", level="ERROR")
    
    def get_size(self) -> int:
        """Получить размер кеша в байтах"""
        total = 0
        try:
            for filename in os.listdir(self.cache_dir):
                filepath = os.path.join(self.cache_dir, filename)
                if os.path.isfile(filepath):
                    total += os.path.getsize(filepath)
        except Exception:
            pass
        return total
