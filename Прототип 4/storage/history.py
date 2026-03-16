# storage/history.py - История озвученных фраз

import os
import config
from utils.logger import log

class HistoryManager:
    """Управление историей озвученных фраз"""
    
    def __init__(self):
        self.history_file = config.HISTORY_FILE
        self.phrases = []
        self.load()
    
    def load(self):
        """Загрузить историю из файла"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.phrases = [line.strip() for line in f if line.strip()]
                log(f"📖 История загружена: {len(self.phrases)} фраз", level="INFO")
            else:
                self.phrases = []
                log("📖 История пуста", level="INFO")
        except Exception as e:
            log(f"❌ Ошибка загрузки истории: {e}", level="ERROR")
            self.phrases = []
    
    def save(self):
        """Сохранить историю в файл"""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                for phrase in self.phrases:
                    f.write(f"{phrase}\n")
            log(f"💾 История сохранена: {len(self.phrases)} фраз", level="DEBUG")
        except Exception as e:
            log(f"❌ Ошибка сохранения истории: {e}", level="ERROR")
    
    def add(self, phrase: str):
        """Добавить фразу в историю"""
        if phrase and phrase not in self.phrases:
            self.phrases.append(phrase)
            if len(self.phrases) > 1000:  # Ограничиваем размер
                self.phrases = self.phrases[-1000:]
            self.save()
    
    def clear(self):
        """Очистить историю"""
        self.phrases = []
        self.save()
        log("🗑️ История очищена", level="INFO")
    
    def get_all(self):
        """Получить всю историю"""
        return self.phrases.copy()
