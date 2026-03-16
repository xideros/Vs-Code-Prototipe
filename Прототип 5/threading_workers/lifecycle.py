# threading_workers/lifecycle.py - Управление жизненным циклом потоков

import threading
from utils.logger import log
from .queues import Queues

class ThreadLifecycle:
    """Управление глобальным состоянием потоков с синхронизацией"""
    
    # === СОБЫТИЯ ДЛЯ СИНХРОНИЗАЦИИ (потокобезопасны!) ===
    _pipeline_running_event = threading.Event()  # Сигнал, что pipeline запущен
    
    # Флаги состояния
    pipeline_session_active = False
    is_paused = False
    
    # Состояние озвучки
    last_spoken_text = None
    last_spoken_text_time = 0.0
    current_playback_text = None
    
    # === БЛОКИРОВКИ ДЛЯ СИНХРОНИЗАЦИИ ===
    _state_lock = threading.Lock()  # Основная блокировка для всех переменных
    _playback_lock = threading.Lock()  # Блокировка для воспроизведения (current_playback_text)
    
    @staticmethod
    def is_pipeline_running():
        """Проверить, запущен ли pipeline (потокобезопасно через Event)."""
        return ThreadLifecycle._pipeline_running_event.is_set()
    
    @classmethod
    def start_session(cls):
        """Запустить новую сессию pipeline."""
        cls.reset_state()
        cls._pipeline_running_event.set()  # Потокобезопасно устанавливаем сигнал
        with cls._state_lock:
            cls.pipeline_session_active = True
            cls.is_paused = False
        log("🔄 Сессия pipeline запущена", level="INFO")
    
    @classmethod
    def stop_session(cls):
        """Остановить сессию pipeline."""
        cls._pipeline_running_event.clear()  # Потокобезопасно очищаем сигнал
        cls.reset_state()
        log("⏹️ Сессия pipeline остановлена", level="INFO")
    
    @classmethod
    def reset_state(cls):
        """Полный сброс состояния"""
        log("🔄 Сброс состояния", level="DEBUG")
        with cls._state_lock:
            cls.pipeline_session_active = False
            cls.is_paused = False
            cls.last_spoken_text = None
            cls.last_spoken_text_time = 0.0
            cls.current_playback_text = None
        Queues.clear_all()
    
    @classmethod
    def pause(cls):
        """Установить паузу"""
        with cls._state_lock:
            cls.is_paused = True
        log("⏸️ Пауза включена", level="INFO")
    
    @classmethod
    def unpause(cls):
        """Убрать паузу"""
        with cls._state_lock:
            cls.is_paused = False
        log("▶️ Пауза отключена", level="INFO")
    
    @classmethod
    def is_active(cls) -> bool:
        """Проверить активность сессии"""
        return cls.is_pipeline_running() and cls.pipeline_session_active
