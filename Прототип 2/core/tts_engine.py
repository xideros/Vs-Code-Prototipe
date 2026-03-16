# core/tts_engine.py - TTS синтез (Edge TTS → MP3)

import os
import asyncio
import tempfile
import edge_tts
import config
from utils.logger import log

class TTSEngine:
    """
    Единственный класс для TTS синтеза.
    Использует Edge TTS для быстрого синтеза русской речи.
    """
    
    def __init__(self):
        """Инициализация TTS движка"""
        self.voice = config.TTS_VOICE
        log(f"✅ TTS инициализирован: {self.voice}", level="INFO")
    
    def synthesize(self, text: str, speed: float = 1.0) -> str:
        """
        Синтезировать речь в MP3 файл
        
        Args:
            text: Текст для синтеза
            speed: Скорость речи (1.0-3.0, где 1.0 = нормальная скорость)
            
        Returns:
            Путь к созданному MP3 файлу или "" при ошибке
        """
        if not text or len(text) < 2:
            log("⚠️ Пустой текст для TTS", level="WARNING")
            return ""
        
        try:
            # Создаём временный файл
            with tempfile.NamedTemporaryFile(
                suffix=".mp3",
                delete=False,
                prefix="voice_"
            ) as f:
                audio_path = f.name
            
            log(f"📝 Синтезируем текст: {text[:40]}...", level="DEBUG")
            log(f"📂 Целевой файл: {audio_path}", level="DEBUG")
            
            # Применяем скорость (speed уже в диапазоне 1.0-3.0)
            # 1.0x = 0%, 2.0x = +100%, 3.0x = +200%
            rate_percent = (speed - 1.0) * 100
            rate_str = f"{rate_percent:+.0f}%"
            
            log(f"⚙️ Скорость: {speed}x (rate={rate_str})", level="DEBUG")
            
            # Синтезируем асинхронно
            try:
                asyncio.run(
                    edge_tts.Communicate(
                        text,
                        voice=self.voice,
                        rate=rate_str
                    ).save(audio_path)
                )
            except Exception as e:
                log(f"❌ Ошибка Edge TTS: {e}", level="ERROR")
                # Очищаем файл при ошибке
                try:
                    os.remove(audio_path)
                except:
                    pass
                return ""
            
            # Проверяем что файл создан и не пустой
            if not os.path.exists(audio_path):
                log(f"❌ Файл не был создан: {audio_path}", level="ERROR")
                return ""
            
            file_size = os.path.getsize(audio_path)
            if file_size == 0:
                log(f"❌ Файл пустой: {audio_path}", level="ERROR")
                try:
                    os.remove(audio_path)
                except:
                    pass
                return ""
            
            log(f"✅ Аудио синтезировано ({file_size} байт): {audio_path}", level="DEBUG")
            return audio_path
            
        except Exception as e:
            log(f"❌ Ошибка TTS синтеза: {e}", level="ERROR")
            import traceback
            log(f"❌ Stacktrace: {traceback.format_exc()}", level="DEBUG")
            return ""
    
    def set_voice(self, voice: str):
        """Изменить голос"""
        self.voice = voice
        log(f"🎤 Голос изменён: {voice}", level="INFO")
