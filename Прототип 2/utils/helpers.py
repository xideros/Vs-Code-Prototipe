# utils/helpers.py - Вспомогательные функции

import hashlib
import config
import os

def normalize_text(text: str) -> str:
    """
    Нормализовать текст (убрать лишние пробелы)
    
    Args:
        text: Исходный текст
        
    Returns:
        Нормализованный текст
    """
    if not text:
        return ""
    
    if config.TEXT_NORMALIZATION_SPACES:
        return ' '.join(text.split())
    return text

def text_preview(text: str, length: int = None) -> str:
    """
    Получить превью текста для логирования
    
    Args:
        text: Исходный текст
        length: Максимальная длина (по-умолчанию из config)
        
    Returns:
        Превью текста
    """
    if length is None:
        length = config.TEXT_PREVIEW_LENGTH
    
    if len(text) <= length:
        return text
    
    return text[:length] + "..."

def get_md5_hash(text: str) -> str:
    """
    Получить MD5 хеш текста (для кеша)
    
    Args:
        text: Исходный текст
        
    Returns:
        MD5 хеш
    """
    return hashlib.md5(text.encode()).hexdigest()

def get_cache_path(text: str) -> str:
    """
    Получить путь кеша для аудиофайла
    
    Args:
        text: Исходный текст
        
    Returns:
        Полный путь к файлу кеша
    """
    md5_hash = get_md5_hash(text)
    filename = f"{md5_hash}.mp3"
    return os.path.join(config.CACHE_DIR, filename)

def ensure_dir(path: str):
    """
    Убедиться что директория существует
    
    Args:
        path: Путь к директории
    """
    os.makedirs(path, exist_ok=True)

def safe_remove(path: str):
    """
    Безопасно удалить файл
    
    Args:
        path: Путь к файлу
    """
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
