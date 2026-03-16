# storage/__init__.py - Персистентность данных

from .history import HistoryManager
from .cache import AudioCache
from .roi_config import ROIConfig
from .settings import SettingsManager

__all__ = [
    'HistoryManager',
    'AudioCache',
    'ROIConfig',
    'SettingsManager',
]
