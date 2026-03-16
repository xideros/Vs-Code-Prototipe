# core/__init__.py - Пакет с бизнес-логикой

from .ocr_engine import OCREngine
from .tts_engine import TTSEngine
from .translator import TextTranslator
from .audio_player import AudioPlayer
from .rnn_text_filter import RNNTextNoiseFilter

__all__ = [
    'OCREngine',
    'TTSEngine', 
    'TextTranslator',
    'AudioPlayer',
    'RNNTextNoiseFilter',
]
