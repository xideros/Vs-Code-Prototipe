#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Главная точка входа приложения Game Subtitle Assistant
Модульная архитектура: все компоненты разделены по файлам
"""

import sys
import atexit
import warnings

warnings.filterwarnings(
    "ignore",
    message=r".*RequestsDependencyWarning.*",
    module=r"requests\..*",
)
warnings.filterwarnings(
    "ignore",
    message=r"urllib3 .* doesn't match a supported version!",
)

from ui import MainWindow
from utils.logger import log, cleanup as cleanup_logger
from threading_workers import ThreadLifecycle, Queues

# Глобальная переменная для доступа к приложению при очистке
_app_instance = None


def configure_windows_dpi_awareness():
    """Включить DPI awareness для стабильной геометрии окна на Windows."""
    if not sys.platform.startswith("win"):
        return

    try:
        import ctypes

        # Windows 8.1+: per-monitor DPI awareness
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            log("🖥️ DPI awareness: Per Monitor (v1)", level="DEBUG")
            return
        except Exception:
            pass

        # Windows 10+: per-monitor v2
        try:
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
            ctypes.windll.user32.SetProcessDpiAwarenessContext(
                DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            )
            log("🖥️ DPI awareness: Per Monitor (v2)", level="DEBUG")
            return
        except Exception:
            pass

        # Старый fallback
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            log("🖥️ DPI awareness: System aware (fallback)", level="DEBUG")
        except Exception:
            pass
    except Exception as e:
        log(f"⚠️ Не удалось применить DPI awareness: {e}", level="WARNING")


def cleanup():
    """Финальная очистка при выходе"""
    global _app_instance
    try:
        log("🧹 Выполняем финальную очистку...", level="INFO")
        
        # Останавливаем сессию
        ThreadLifecycle.stop_session()
        
        # Очищаем очереди
        Queues.clear_all()
        
        # ✅ Очищаем pygame.mixer и другие ресурсы
        if _app_instance:
            try:
                _app_instance.audio_player.cleanup()
                log("✅ AudioPlayer очищен", level="DEBUG")
            except Exception as e:
                log(f"⚠️ Ошибка при очистке AudioPlayer: {e}", level="WARNING")
        
        # ✅ Очищаем логгер (закрываем файловые дескрипторы)
        try:
            cleanup_logger()
            log("✅ Logger очищен", level="DEBUG")
        except Exception as e:
            log(f"⚠️ Ошибка при очистке Logger: {e}", level="WARNING")
        
        log("✅ Очистка завершена", level="INFO")
    except Exception as e:
        print(f"⚠️ Ошибка при очистке: {e}")


def main():
    """Главная функция"""
    global _app_instance
    try:
        configure_windows_dpi_awareness()
        log("🚀 Game Subtitle Assistant запущена", level="INFO")
        
        # Регистрируем atexit для очистки
        atexit.register(cleanup)
        
        # Создаём и запускаем главное окно
        _app_instance = MainWindow()
        _app_instance.root.mainloop()
        
    except Exception as e:
        log(f"❌ Критическая ошибка: {e}", level="ERROR")
        sys.exit(1)


if __name__ == "__main__":
    main()
