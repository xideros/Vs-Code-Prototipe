# storage/__init__.py - Персистентность данных

from .history import HistoryManager
from .cache import AudioCache
from .settings import SettingsManager

__all__ = [
    'HistoryManager',
    'AudioCache',
    'SettingsManager',
]
