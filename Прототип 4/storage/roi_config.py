# storage/roi_config.py - Сохранение региона захвата (ROI)

import os
import config
from utils.logger import log

class ROIConfig:
    """Сохранение и загрузка конфигурации региона захвата"""
    
    def __init__(self):
        self.config_file = config.CONFIG_FILE
        self.roi = None
        self.load()
    
    def load(self) -> bool:
        """
        Загрузить ROI из файла
        
        Returns:
            True если успешно, False если файл не существует
        """
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    line = f.read().strip()
                    x, y, w, h = map(int, line.split(','))
                    self.roi = (x, y, w, h)
                    log(f"📍 ROI загружен: {self.roi}", level="INFO")
                    return True
            else:
                log("📍 Конфиг ROI не найден", level="WARNING")
                self.roi = None
                return False
        except Exception as e:
            log(f"❌ Ошибка загрузки ROI: {e}", level="ERROR")
            self.roi = None
            return False
    
    def save(self, roi: tuple):
        """
        Сохранить ROI в файл
        
        Args:
            roi: Кортеж (x, y, width, height)
        """
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            x, y, w, h = roi
            with open(self.config_file, 'w') as f:
                f.write(f"{x},{y},{w},{h}")
            self.roi = roi
            log(f"💾 ROI сохранён: {roi}", level="INFO")
        except Exception as e:
            log(f"❌ Ошибка сохранения ROI: {e}", level="ERROR")
    
    def get(self) -> tuple:
        """
        Получить ROI
        
        Returns:
            Кортеж (x, y, width, height) или None
        """
        return self.roi
    
    def is_configured(self) -> bool:
        """Проверить, настроен ли ROI"""
        return self.roi is not None
    
    def clear(self):
        """Очистить конфиг"""
        try:
            if os.path.exists(self.config_file):
                os.remove(self.config_file)
            self.roi = None
            log("🗑️ ROI конфиг удалён", level="INFO")
        except Exception as e:
            log(f"❌ Ошибка удаления ROI: {e}", level="ERROR")
