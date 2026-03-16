# core/ocr_engine.py - OCR обработка (backend-архитектура Прототипа 3)

import os
import re
import tempfile

import config
from utils.logger import log
from .ocr_backends import build_backend

class OCREngine:
    """
    Единая точка входа OCR в Прототипе 3.
    Поддерживает backend-подход: auto/tesseract/easyocr/paddleocr.
    """
    
    def __init__(self):
        """Инициализация OCR движка"""
        self.backend = None
        self.backend_name = None
        self.profile_name = self._get_profile_name()
        self.profile = self._get_profile_settings(self.profile_name)
        self._cv2 = self._try_import_cv2()
        self._init_backend()

        log(
            f"ℹ️ OCR профиль: {self.profile_name} (preprocess={self.profile.get('preprocess', False)})",
            level="INFO",
        )

    def _get_profile_name(self) -> str:
        profile_name = getattr(config, "OCR_PROFILE", "balanced")
        profile_name = (profile_name or "balanced").strip().lower()
        presets = getattr(config, "OCR_PROFILE_PRESETS", {})
        if profile_name not in presets:
            return "balanced"
        return profile_name

    def _get_profile_settings(self, profile_name: str) -> dict:
        presets = getattr(config, "OCR_PROFILE_PRESETS", {})
        base = {
            "preprocess": True,
            "upscale": 1.0,
            "threshold": "none",
            "denoise": False,
            "clahe": False,
            "sharpen": False,
            "normalize_spaces": True,
            "merge_hyphen_wrap": True,
            "min_chars": 2,
            "min_alpha_ratio": 0.2,
        }
        selected = presets.get(profile_name, {})
        base.update(selected)
        return base

    def _try_import_cv2(self):
        try:
            import cv2

            return cv2
        except Exception:
            return None

    def _init_backend(self):
        """Инициализировать OCR backend согласно config.OCR_BACKEND."""
        requested = getattr(config, "OCR_BACKEND", "auto")
        requested = (requested or "auto").lower().strip()

        if requested == "auto":
            candidates = list(getattr(config, "OCR_BACKEND_PRIORITY", ["tesseract", "easyocr"]))
        else:
            candidates = [requested]

        for name in candidates:
            backend = build_backend(name)
            if backend and backend.available():
                self.backend = backend
                self.backend_name = backend.name
                log(f"✅ OCR backend выбран: {self.backend_name}", level="INFO")
                return

        # Совместимость с legacy-конфигом, если новые параметры не помогли.
        legacy_name = "tesseract" if getattr(config, "USE_TESSERACT", True) else "easyocr"
        backend = build_backend(legacy_name)
        if backend and backend.available():
            self.backend = backend
            self.backend_name = backend.name
            log(f"✅ OCR backend (legacy fallback): {self.backend_name}", level="INFO")
            return

        raise RuntimeError("Не удалось инициализировать OCR backend")
    
    def recognize(self, image_path: str) -> str:
        """
        Распознать текст на изображении
        
        Args:
            image_path: Путь к скриншоту
            
        Returns:
            Распознанный текст
        """
        image_input = image_path
        if isinstance(image_input, str):
            if not os.path.exists(image_input):
                log(f"⚠️ Файл не найден: {image_input}", level="WARNING")
                return ""

        ocr_image_input, temp_path = self._prepare_image_for_profile(image_input)

        try:
            if not self.backend:
                return ""

            if isinstance(ocr_image_input, str):
                raw_text = self.backend.recognize(ocr_image_input)
            else:
                raw_text = self.backend.recognize_array(ocr_image_input)
                if not raw_text:
                    raw_text = self._recognize_array_via_tempfile(ocr_image_input)

            processed = self._postprocess_text(raw_text)
            if processed:
                return processed

            # Fallback: иногда "жесткая" предобработка съедает символы.
            # Повторяем распознавание на исходном кадре.
            if self.profile.get("preprocess", False):
                if isinstance(image_input, str):
                    raw_text_fallback = self.backend.recognize(image_input)
                else:
                    raw_text_fallback = self.backend.recognize_array(image_input)
                    if not raw_text_fallback:
                        raw_text_fallback = self._recognize_array_via_tempfile(image_input)

                return self._postprocess_text(raw_text_fallback)

            return ""
        except Exception as e:
            log(f"❌ Ошибка распознавания: {e}", level="ERROR")
            return ""
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def _prepare_image_for_profile(self, image_input):
        """Подготовить изображение под текущий OCR профиль."""
        if not self.profile.get("preprocess", False):
            return image_input, None
        if self._cv2 is None:
            return image_input, None

        cv2 = self._cv2
        if isinstance(image_input, str):
            img = cv2.imread(image_input, cv2.IMREAD_GRAYSCALE)
        else:
            # Screenshot loop передает RGB кадры из mss.
            img = image_input
            if img is not None and len(getattr(img, "shape", ())) == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        if img is None:
            return image_input, None

        upscale = float(self.profile.get("upscale", 1.0) or 1.0)
        if upscale > 1.0:
            img = cv2.resize(img, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)

        if self.profile.get("denoise", False):
            img = cv2.medianBlur(img, 3)

        if self.profile.get("clahe", False):
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            img = clahe.apply(img)

        threshold_mode = str(self.profile.get("threshold", "none")).lower()
        if threshold_mode == "otsu":
            _, img = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        elif threshold_mode == "adaptive":
            img = cv2.adaptiveThreshold(
                img,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                21,
                11,
            )

        if self.profile.get("sharpen", False):
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, kernel)

        if isinstance(image_input, str):
            fd, temp_path = tempfile.mkstemp(prefix="ocr_pre_", suffix=".png")
            os.close(fd)
            ok = cv2.imwrite(temp_path, img)
            if not ok:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
                return image_input, None
            return temp_path, temp_path

        return img, None

    def _recognize_array_via_tempfile(self, image_array) -> str:
        """Fallback для backend-ов, которые не принимают array напрямую."""
        if self._cv2 is None or image_array is None:
            return ""

        fd, temp_path = tempfile.mkstemp(prefix="ocr_arr_", suffix=".png")
        os.close(fd)
        try:
            if not self._cv2.imwrite(temp_path, image_array):
                return ""
            return self.backend.recognize(temp_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def _postprocess_text(self, text: str) -> str:
        """Постобработка OCR текста в зависимости от профиля."""
        if not text:
            return ""

        processed = text
        processed = processed.replace("\r", " ").replace("\n", " ")

        if self.profile.get("merge_hyphen_wrap", True):
            processed = re.sub(r"(\w)-\s+(\w)", r"\1\2", processed)

        if self.profile.get("normalize_spaces", True):
            processed = " ".join(processed.split())
        else:
            processed = processed.strip()

        min_chars = int(self.profile.get("min_chars", 0) or 0)
        if len(processed) < min_chars:
            return ""

        alpha_count = sum(1 for ch in processed if ch.isalpha())
        min_alpha_ratio = float(self.profile.get("min_alpha_ratio", 0.0) or 0.0)
        if processed:
            alpha_ratio = alpha_count / len(processed)
            if alpha_ratio < min_alpha_ratio:
                return ""

        return processed
    
    def is_available(self) -> bool:
        """Проверить доступность OCR"""
        return self.backend is not None
    
    def cleanup(self):
        """Очистить ресурсы backend"""
        try:
            if self.backend:
                self.backend.cleanup()
        except Exception as e:
            log(f"⚠️ Ошибка при очистке OCR backend: {e}", level="WARNING")
