# core/ocr_engine.py - OCR обработка (Tesseract + EasyOCR)

import os
import cv2
import numpy as np
import pytesseract
import easyocr
from PIL import Image as PILImage
import config
from utils.logger import log

class OCREngine:
    """
    Единственный класс для OCR.
    Выбирает между Tesseract (быстро) и EasyOCR (fallback).
    """
    
    def __init__(self):
        """Инициализация OCR движка"""
        self.use_tesseract = config.USE_TESSERACT
        self.tesseract_path = None
        self.easyocr_reader = None
        
        # Ищем Tesseract
        if self.use_tesseract:
            self._init_tesseract()
        else:
            self._init_easyocr()
    
    def _init_tesseract(self):
        """Инициализация Tesseract"""
        for path in config.TESSERACT_PATHS:
            if os.path.exists(path):
                pytesseract.pytesseract.pytesseract_cmd = path
                self.tesseract_path = path
                log(f"✅ Tesseract найден: {path}", level="INFO")
                return
        
        # Fallback на EasyOCR если Tesseract не найден
        log("⚠️ Tesseract не найден, переходим на EasyOCR", level="WARNING")
        self.use_tesseract = False
        self._init_easyocr()
    
    def _init_easyocr(self):
        """Инициализация EasyOCR с fallback'ом на CPU"""
        log("🚀 Инициализация EasyOCR (может занять время)...", level="INFO")
        
        # Пытаемся инициализировать с текущей конфигурацией
        try:
            self.easyocr_reader = easyocr.Reader(
                config.EASYOCR_LANGUAGES,
                gpu=config.EASYOCR_USE_GPU
            )
            gpu_info = "GPU" if config.EASYOCR_USE_GPU else "CPU"
            log(f"✅ EasyOCR инициализирован ({gpu_info})", level="INFO")
        except Exception as e:
            # Если GPU конфигурация не работает, пробуем CPU
            if config.EASYOCR_USE_GPU:
                log(f"⚠️ GPU для EasyOCR недоступна, переходим на CPU: {e}", level="WARNING")
                try:
                    self.easyocr_reader = easyocr.Reader(
                        config.EASYOCR_LANGUAGES,
                        gpu=False
                    )
                    log(f"✅ EasyOCR инициализирован (CPU fallback)", level="INFO")
                except Exception as e2:
                    log(f"❌ Ошибка инициализации EasyOCR даже на CPU: {e2}", level="ERROR")
                    raise
            else:
                log(f"❌ Ошибка инициализации EasyOCR на CPU: {e}", level="ERROR")
                raise
    
    def recognize(self, image_path: str) -> str:
        """
        Распознать текст на изображении
        
        Args:
            image_path: Путь к скриншоту
            
        Returns:
            Распознанный текст
        """
        if not os.path.exists(image_path):
            log(f"⚠️ Файл не найден: {image_path}", level="WARNING")
            return ""
        
        try:
            if self.use_tesseract:
                return self._recognize_tesseract(image_path)
            else:
                return self._recognize_easyocr(image_path)
        except Exception as e:
            log(f"❌ Ошибка распознавания: {e}", level="ERROR")
            return ""
    
    def _recognize_tesseract(self, image_path: str) -> str:
        """Распознавание с Tesseract"""
        try:
            img = PILImage.open(image_path)
            text = pytesseract.image_to_string(img, lang='+'.join(config.OCR_LANGUAGES))
            return text.strip()
        except Exception as e:
            log(f"❌ Ошибка Tesseract: {e}", level="ERROR")
            # Fallback на EasyOCR
            self.use_tesseract = False
            if self.easyocr_reader is None:
                self._init_easyocr()
            return self._recognize_easyocr(image_path)
    
    def _recognize_easyocr(self, image_path: str) -> str:
        """Распознавание с EasyOCR"""
        if self.easyocr_reader is None:
            self._init_easyocr()
        
        try:
            img = cv2.imread(image_path)
            results = self.easyocr_reader.readtext(img, detail=0)
            text = ' '.join(results)
            return text.strip()
        except Exception as e:
            log(f"❌ Ошибка EasyOCR: {e}", level="ERROR")
            return ""
    
    def is_available(self) -> bool:
        """Проверить доступность OCR"""
        return self.tesseract_path is not None or self.easyocr_reader is not None
    
    def cleanup(self):
        """Очистить ресурсы (особенно EasyOCR)"""
        try:
            if self.easyocr_reader is not None:
                # Явно удаляем ридер для освобождения памяти (особенно GPU памяти)
                try:
                    del self.easyocr_reader
                except:
                    pass
                self.easyocr_reader = None
                log("✅ EasyOCR ридер удален из памяти", level="DEBUG")
        except Exception as e:
            log(f"⚠️ Ошибка при очистке EasyOCR: {e}", level="WARNING")
