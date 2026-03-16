# core/__init__.py - Пакет с бизнес-логикой

from .tts_engine import TTSEngine
from .translator import TextTranslator
from .audio_player import AudioPlayer

__all__ = [
    'TTSEngine', 
    'TextTranslator',
    'AudioPlayer',
]
