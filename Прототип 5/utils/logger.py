# utils/logger.py - Централизованное логирование

import os
import sys
import config
from datetime import datetime


def _safe_reconfigure_stream(stream):
    """Best-effort UTF-8 stream reconfiguration for Windows consoles."""
    try:
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        # Never fail app startup because of console encoding issues.
        pass


# Configure UTF-8 output as early as possible.
_safe_reconfigure_stream(sys.stdout)
_safe_reconfigure_stream(sys.stderr)

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

        self._configure_console_encoding()
        
        # Если логирование в файл включено, убедимся, что файл существует
        if self.log_file:
            try:
                # Просто создаем пустой файл, если его нет (с обработкой ошибок кодировки)
                with open(self.log_file, 'a', encoding='utf-8', errors='replace'):
                    pass
            except Exception as e:
                print(f"❌ Ошибка создания логгера: {e}")

    def _configure_console_encoding(self):
        """Настроить UTF-8 вывод в консоль, особенно для Windows терминала."""
        try:
            if os.name == 'nt':
                try:
                    import ctypes

                    # Переключаем code page консоли на UTF-8.
                    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
                    ctypes.windll.kernel32.SetConsoleCP(65001)
                except Exception:
                    pass

            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            # Не блокируем запуск приложения из-за настройки консоли.
            pass

    def _safe_console_print(self, formatted: str):
        """Печатать строку в консоль без падений на проблемной кодировке."""
        try:
            print(formatted)
        except UnicodeEncodeError:
            try:
                if os.name == 'nt':
                    fallback = formatted.encode('cp1251', 'replace').decode('cp1251')
                else:
                    fallback = formatted.encode('utf-8', 'replace').decode('utf-8')
                print(fallback)
            except Exception:
                pass
        except Exception:
            pass
    
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
                # Самый надежный вывод для Windows-консолей: пишем байты UTF-8 напрямую.
                payload = (formatted + "\n").encode("utf-8", "replace")
                stdout = sys.stdout
                if stdout and hasattr(stdout, "buffer") and stdout.buffer:
                    stdout.buffer.write(payload)
                    stdout.flush()
                else:
                    # Редкий fallback (например, нестандартный stdout без buffer).
                    self._safe_console_print(formatted)
            except Exception:
                # На случай экзотического stdout делаем последнюю попытку через print.
                self._safe_console_print(formatted)
        
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
