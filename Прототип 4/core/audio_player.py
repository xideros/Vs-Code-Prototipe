# core/audio_player.py - Воспроизведение аудио с pygame.mixer (полный контроль)

import os
import threading
import config
from utils.logger import log

try:
    import pygame
    PYGAME_AVAILABLE = True
except Exception as e:
    log(f"⚠️ pygame.mixer недоступен: {e}", level="WARNING")
    PYGAME_AVAILABLE = False

class AudioPlayer:
    """
    Единственный класс для воспроизведения аудио.
    Использует pygame.mixer для полного контроля: pause, unpause, stop, volume.
    """
    
    def __init__(self):
        """Инициализация аудио плеера"""
        if not PYGAME_AVAILABLE:
            log("⚠️ pygame.mixer недоступен, функциональность ограничена", level="WARNING")
        
        self.current_channel = None  # Текущий канал воспроизведения
        self.is_playing = False
        self.is_paused = False
        self.volume = config.AUDIO_VOLUME_DEFAULT / 100.0
        self.play_lock = threading.Lock()  # Синхронизация доступа
        self._ensure_mixer_ready()
        
        log("✅ AudioPlayer инициализирован", level="INFO")

    def _ensure_mixer_ready(self) -> bool:
        """Убедиться, что mixer инициализирован и готов к воспроизведению."""
        if not PYGAME_AVAILABLE:
            return False

        try:
            if pygame.mixer.get_init():
                return True

            pygame.mixer.pre_init(
                frequency=int(getattr(config, "AUDIO_SAMPLERATE", 44100)),
                size=-16,
                channels=int(getattr(config, "AUDIO_CHANNELS", 2)),
                buffer=1024,
            )
            pygame.mixer.init(
                frequency=int(getattr(config, "AUDIO_SAMPLERATE", 44100)),
                size=-16,
                channels=int(getattr(config, "AUDIO_CHANNELS", 2)),
                buffer=1024,
            )
            log(f"🔊 pygame.mixer инициализирован: {pygame.mixer.get_init()}", level="INFO")
            return True
        except Exception as e:
            log(f"❌ Не удалось инициализировать pygame.mixer: {e}", level="ERROR")
            return False

    def _reinit_mixer(self) -> bool:
        """Жёсткий reset mixer при тихом сбое воспроизведения."""
        if not PYGAME_AVAILABLE:
            return False

        try:
            pygame.mixer.quit()
        except Exception:
            pass
        return self._ensure_mixer_ready()

    def _stop_unlocked(self):
        """Остановить воспроизведение (только внутри уже взятого lock)."""
        try:
            if PYGAME_AVAILABLE:
                pygame.mixer.music.stop()
        except Exception:
            pass
        self.current_channel = None
        self.is_playing = False
        self.is_paused = False
    
    def play(self, audio_path: str, blocking: bool = False) -> bool:
        """
        Воспроизвести аудиофайл с полным контролем
        
        Args:
            audio_path: Путь к аудиофайлу (MP3, WAV, OGG)
            blocking: Ждать завершения воспроизведения
            
        Returns:
            True если успешно, False если ошибка
        """
        if not os.path.exists(audio_path):
            log(f"❌ Файл не найден: {audio_path}", level="ERROR")
            return False
        
        if not PYGAME_AVAILABLE:
            log("❌ pygame.mixer недоступен", level="ERROR")
            return False

        if not self._ensure_mixer_ready():
            log("❌ pygame.mixer не готов к воспроизведению", level="ERROR")
            return False
        
        try:
            with self.play_lock:
                # Останавливаем предыдущее воспроизведение без повторного захвата lock
                self._stop_unlocked()
                
                log(f"📂 Загружаем файл: {audio_path}", level="DEBUG")
                
                # Используем pygame.mixer.music для лучшей поддержки MP3
                pygame.mixer.music.load(audio_path)
                pygame.mixer.music.set_volume(self.volume)
                pygame.mixer.music.play()

                pygame.time.wait(120)
                if not pygame.mixer.music.get_busy():
                    log("⚠️ Воспроизведение не стартовало, пробуем переинициализировать mixer", level="WARNING")
                    if not self._reinit_mixer():
                        return False
                    pygame.mixer.music.load(audio_path)
                    pygame.mixer.music.set_volume(self.volume)
                    pygame.mixer.music.play()
                    pygame.time.wait(120)
                    if not pygame.mixer.music.get_busy():
                        log("❌ Файл загружен, но звук не стартует", level="ERROR")
                        return False
                
                self.is_playing = True
                self.is_paused = False
                
                log(f"▶️ Файл воспроизведения: {os.path.basename(audio_path)}", level="DEBUG")
                log(f"🔊 Громкость playback: {int(self.volume * 100)}%", level="INFO")

            if blocking:
                # Ждём завершения воспроизведения без удержания play_lock,
                # чтобы stop() мог прервать звук мгновенно.
                while pygame.mixer.music.get_busy():
                    pygame.time.wait(100)

                with self.play_lock:
                    self.is_playing = False
            
            return True
            
        except Exception as e:
            log(f"❌ Ошибка воспроизведения: {e}", level="ERROR")
            import traceback
            traceback.print_exc()
            log(f"❌ Stacktrace: {traceback.format_exc()}", level="DEBUG")
            self.is_playing = False
            return False
    
    def stop(self):
        """Полностью остановить воспроизведение"""
        with self.play_lock:
            self._stop_unlocked()
            log("⏹️ Воспроизведение остановлено", level="DEBUG")
    
    def pause(self):
        """Пауза (сохраняет позицию)"""
        if not PYGAME_AVAILABLE:
            log("⚠️ pygame.mixer недоступен, пауза недоступна", level="WARNING")
            return
        
        with self.play_lock:
            if self.is_playing and not self.is_paused:
                try:
                    pygame.mixer.music.pause()
                    self.is_paused = True
                    self.is_playing = False
                    log("⏸️ Пауза (позиция сохранена)", level="DEBUG")
                except Exception as e:
                    log(f"⚠️ Ошибка паузы: {e}", level="WARNING")
    
    def unpause(self):
        """Возобновить с позиции паузы"""
        if not PYGAME_AVAILABLE:
            log("⚠️ pygame.mixer недоступен, возобновление недоступно", level="WARNING")
            return
        
        with self.play_lock:
            if self.is_paused:
                try:
                    pygame.mixer.music.unpause()
                    self.is_paused = False
                    self.is_playing = True
                    log("▶️ Возобновление со слова паузы", level="DEBUG")
                except Exception as e:
                    log(f"⚠️ Ошибка возобновления: {e}", level="WARNING")
    
    def set_volume(self, volume: int):
        """
        Установить громкость (0-100)
        
        Args:
            volume: Громкость в процентах
        """
        if not PYGAME_AVAILABLE:
            log("⚠️ pygame.mixer недоступен, управление громкостью недоступна", level="WARNING")
            return
        
        volume = max(config.AUDIO_VOLUME_MIN, min(volume, config.AUDIO_VOLUME_MAX))
        self.volume = volume / 100.0
        
        with self.play_lock:
            try:
                pygame.mixer.music.set_volume(self.volume)
            except:
                pass
        
        log(f"🔊 Громкость: {volume}%", level="DEBUG")
    
    def get_volume(self) -> int:
        """Получить текущую громкость"""
        return int(self.volume * 100)
    
    def is_busy(self) -> bool:
        """Проверить, идёт ли воспроизведение или пауза"""
        return self.is_playing or self.is_paused
    
    def cleanup(self):
        """Очистить ресурсы"""
        self.stop()
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.stop()
                pygame.mixer.quit()
            except:
                pass
        log("✅ AudioPlayer очищен", level="INFO")
