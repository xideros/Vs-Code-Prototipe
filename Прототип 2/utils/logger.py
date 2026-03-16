# utils/logger.py - Централизованное логирование

import os
import config
from datetime import datetime

class Logger:
    """Единственный логгер для приложения"""
    
    LEVELS = {
        'DEBUG': 0,
        'INFO': 1,
        'WARNING': 2,
        'ERROR': 3,
    }
    
    EMOJIS = {
        'DEBUG': '🔍',
        'INFO': 'ℹ️',
        'WARNING': '⚠️',
        'ERROR': '❌',
    }
    
    def __init__(self):
        self.current_level = self.LEVELS.get(config.LOG_LEVEL, 1)
        self.log_file = config.LOG_FILE if config.LOG_TO_FILE else None
        self.to_console = True
        self.to_file = config.LOG_TO_FILE
        
        # Если логирование в файл включено, убедимся, что файл существует
        if self.log_file:
            try:
                # Просто создаем пустой файл, если его нет (с обработкой ошибок кодировки)
                with open(self.log_file, 'a', encoding='utf-8', errors='replace'):
                    pass
            except Exception as e:
                print(f"❌ Ошибка создания логгера: {e}")
    
    def log(self, message: str, level: str = "INFO"):
        """Логировать сообщение"""
        
        # Проверяем уровень
        if self.LEVELS.get(level, 1) < self.current_level:
            return
        
        # Форматируем сообщение
        emoji = self.EMOJIS.get(level, '')
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"{emoji} [{timestamp}] {message}"
        
        # Выводим в консоль
        if self.to_console:
            try:
                print(formatted)
            except:
                # В случае проблем с кодировкой консоли, пропускаем
                pass
        
        # Пишем в файл (с обработкой ошибок кодировки)
        if self.to_file and self.log_file:
            try:
                with open(self.log_file, 'a', encoding='utf-8', errors='replace') as f:
                    f.write(f"[{timestamp}] {level}: {message}\n")
                    f.flush()  # Убедимся, что данные записаны на диск
            except Exception as e:
                print(f"❌ Ошибка записи в лог: {e}")
    
    def cleanup(self):
        """Очистить ресурсы логгера (нет явно открытых дескрипторов)"""
        # Логгер использует context manager для каждой записи,
        # поэтому нет явно открытых файловых дескрипторов для закрытия
        pass

# Глобальный логгер
_logger = Logger()

def log(message: str, level: str = "INFO"):
    """Глобальная функция логирования"""
    _logger.log(message, level)

def set_level(level: str):
    """Установить уровень логирования"""
    _logger.current_level = _logger.LEVELS.get(level, 1)
    log(f"📋 Уровень логирования: {level}", level="INFO")

def cleanup():
    """Очистить ресурсы логгера"""
    _logger.cleanup()
