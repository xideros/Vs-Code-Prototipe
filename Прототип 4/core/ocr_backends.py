# core/ocr_backends.py - Backends OCR для Прототипа 3

import os
from abc import ABC, abstractmethod

import config
from utils.logger import log


class OCRBackendBase(ABC):
    """Базовый интерфейс OCR backend."""

    name = "base"

    @abstractmethod
    def available(self) -> bool:
        """Доступен ли backend в текущем окружении."""
        raise NotImplementedError

    @abstractmethod
    def recognize(self, image_path: str) -> str:
        """Распознать текст из изображения."""
        raise NotImplementedError

    def recognize_array(self, image_array) -> str:
        """Распознать текст из массива изображения (H, W, C)."""
        return ""

    def cleanup(self):
        """Освободить ресурсы backend (опционально)."""
        return


class TesseractBackend(OCRBackendBase):
    name = "tesseract"

    def __init__(self):
        self._pytesseract = None
        self._pil_image = None
        self.tesseract_path = None

        try:
            import pytesseract
            from PIL import Image as PILImage

            self._pytesseract = pytesseract
            self._pil_image = PILImage

            for path in config.TESSERACT_PATHS:
                if os.path.exists(path):
                    self._pytesseract.pytesseract.pytesseract_cmd = path
                    self.tesseract_path = path
                    break
        except Exception as e:
            log(f"⚠️ Tesseract backend недоступен: {e}", level="WARNING")

    def available(self) -> bool:
        return self._pytesseract is not None and self._pil_image is not None and self.tesseract_path is not None

    def _tesseract_config(self) -> str:
        oem = int(getattr(config, "TESSERACT_OEM", 3))
        psm = int(getattr(config, "TESSERACT_PSM", 6))
        return f"--oem {oem} --psm {psm}"

    def _tesseract_config_for_psm(self, psm: int) -> str:
        oem = int(getattr(config, "TESSERACT_OEM", 3))
        return f"--oem {oem} --psm {int(psm)}"

    def _text_quality_score(self, text: str) -> float:
        if not text:
            return 0.0
        letters = sum(1 for ch in text if ch.isalpha())
        digits = sum(1 for ch in text if ch.isdigit())
        spaces = sum(1 for ch in text if ch.isspace())
        length = len(text)
        return (letters * 1.2 + digits * 0.4 + spaces * 0.2) / max(1, length)

    def _best_text_across_psm(self, pil_img) -> str:
        if bool(getattr(config, "TESSERACT_FAST_MODE", False)):
            cfg = self._tesseract_config_for_psm(int(getattr(config, "TESSERACT_PSM", 6)))
            use_conf = bool(getattr(config, "TESSERACT_FAST_USE_CONFIDENCE", False))
            try:
                if use_conf:
                    text = self._extract_text_confident(pil_img, cfg)
                    if text:
                        return text.strip()
                text = self._pytesseract.image_to_string(
                    pil_img,
                    lang='+'.join(config.OCR_LANGUAGES),
                    config=cfg,
                )
                return (text or "").strip()
            except Exception:
                return ""

        psm_candidates = list(getattr(config, "TESSERACT_PSM_CANDIDATES", [getattr(config, "TESSERACT_PSM", 6)]))
        best_text = ""
        best_score = 0.0

        for psm in psm_candidates:
            cfg = self._tesseract_config_for_psm(psm)

            try:
                text_conf = self._extract_text_confident(pil_img, cfg)
                score_conf = self._text_quality_score(text_conf)
                if score_conf > best_score:
                    best_text = text_conf
                    best_score = score_conf
            except Exception:
                pass

            if best_score < 0.35:
                try:
                    text_plain = self._pytesseract.image_to_string(
                        pil_img,
                        lang='+'.join(config.OCR_LANGUAGES),
                        config=cfg,
                    ).strip()
                    score_plain = self._text_quality_score(text_plain)
                    if score_plain > best_score:
                        best_text = text_plain
                        best_score = score_plain
                except Exception:
                    pass

        return best_text.strip()

    def _extract_text_confident(self, pil_img, tcfg: str | None = None) -> str:
        conf_min = int(getattr(config, "TESSERACT_MIN_CONF", 45))
        if tcfg is None:
            tcfg = self._tesseract_config()
        data = self._pytesseract.image_to_data(
            pil_img,
            lang='+'.join(config.OCR_LANGUAGES),
            config=tcfg,
            output_type=self._pytesseract.Output.DICT,
        )

        words = []
        texts = data.get("text", [])
        confs = data.get("conf", [])
        for i in range(len(texts)):
            raw = (texts[i] or "").strip()
            if not raw:
                continue
            try:
                conf = int(float(confs[i]))
            except Exception:
                conf = -1
            if conf >= conf_min:
                words.append(raw)

        if words:
            return " ".join(words).strip()
        return ""

    def recognize(self, image_path: str) -> str:
        if not self.available() or not os.path.exists(image_path):
            return ""

        try:
            img = self._pil_image.open(image_path)
            text = self._best_text_across_psm(img)
            return text.strip()
        except Exception as e:
            log(f"❌ Ошибка Tesseract: {e}", level="ERROR")
            return ""

    def recognize_array(self, image_array) -> str:
        if not self.available() or image_array is None:
            return ""

        try:
            img = self._pil_image.fromarray(image_array)
            text = self._best_text_across_psm(img)
            return text.strip()
        except Exception as e:
            log(f"❌ Ошибка Tesseract (array): {e}", level="ERROR")
            return ""


class EasyOCRBackend(OCRBackendBase):
    name = "easyocr"

    def __init__(self):
        self._cv2 = None
        self._easyocr = None
        self.reader = None

        try:
            import cv2
            import easyocr

            self._cv2 = cv2
            self._easyocr = easyocr
        except Exception as e:
            log(f"⚠️ EasyOCR backend недоступен: {e}", level="WARNING")
            return

        self._init_reader()

    def _init_reader(self):
        if self._easyocr is None:
            return

        try:
            self.reader = self._easyocr.Reader(
                config.EASYOCR_LANGUAGES,
                gpu=config.EASYOCR_USE_GPU,
            )
            gpu_info = "GPU" if config.EASYOCR_USE_GPU else "CPU"
            log(f"✅ EasyOCR backend инициализирован ({gpu_info})", level="INFO")
        except Exception as e:
            if config.EASYOCR_USE_GPU:
                log(f"⚠️ EasyOCR GPU недоступен, fallback на CPU: {e}", level="WARNING")
                try:
                    self.reader = self._easyocr.Reader(
                        config.EASYOCR_LANGUAGES,
                        gpu=False,
                    )
                    log("✅ EasyOCR backend инициализирован (CPU fallback)", level="INFO")
                except Exception as e2:
                    log(f"❌ Ошибка инициализации EasyOCR: {e2}", level="ERROR")
                    self.reader = None
            else:
                log(f"❌ Ошибка инициализации EasyOCR: {e}", level="ERROR")
                self.reader = None

    def available(self) -> bool:
        return self._cv2 is not None and self.reader is not None

    def recognize(self, image_path: str) -> str:
        if not self.available() or not os.path.exists(image_path):
            return ""

        try:
            img = self._cv2.imread(image_path)
            results = self.reader.readtext(img, detail=0)
            return ' '.join(results).strip()
        except Exception as e:
            log(f"❌ Ошибка EasyOCR: {e}", level="ERROR")
            return ""

    def recognize_array(self, image_array) -> str:
        if not self.available() or image_array is None:
            return ""

        try:
            results = self.reader.readtext(image_array, detail=0)
            return ' '.join(results).strip()
        except Exception as e:
            log(f"❌ Ошибка EasyOCR (array): {e}", level="ERROR")
            return ""

    def cleanup(self):
        if self.reader is not None:
            try:
                del self.reader
            except Exception:
                pass
            self.reader = None


class PaddleOCRBackend(OCRBackendBase):
    name = "paddleocr"

    def __init__(self):
        self._ocr = None
        self._paddleocr_cls = None

        try:
            from paddleocr import PaddleOCR

            self._paddleocr_cls = PaddleOCR
        except Exception as e:
            log(f"⚠️ PaddleOCR backend недоступен: {e}", level="WARNING")
            return

        # Каркас: инициализируем в базовом режиме, если библиотека установлена.
        try:
            self._ocr = self._paddleocr_cls(use_doc_orientation_classify=False)
            log("✅ PaddleOCR backend инициализирован", level="INFO")
        except Exception as e:
            log(f"❌ Ошибка инициализации PaddleOCR: {e}", level="ERROR")
            self._ocr = None

    def available(self) -> bool:
        return self._ocr is not None

    def recognize(self, image_path: str) -> str:
        if not self.available() or not os.path.exists(image_path):
            return ""

        try:
            result = self._ocr.predict(input=image_path)
            lines = []
            for item in result:
                rec_texts = item.get('rec_texts', [])
                if rec_texts:
                    lines.extend(rec_texts)
            return ' '.join(lines).strip()
        except Exception as e:
            log(f"❌ Ошибка PaddleOCR: {e}", level="ERROR")
            return ""

    def recognize_array(self, image_array) -> str:
        if not self.available() or image_array is None:
            return ""

        try:
            result = self._ocr.predict(input=image_array)
            lines = []
            for item in result:
                rec_texts = item.get('rec_texts', [])
                if rec_texts:
                    lines.extend(rec_texts)
            return ' '.join(lines).strip()
        except Exception:
            # Не все версии PaddleOCR корректно принимают numpy array.
            return ""


def build_backend(name: str):
    """Фабрика OCR backend по имени."""
    name = (name or "").lower().strip()
    mapping = {
        "tesseract": TesseractBackend,
        "easyocr": EasyOCRBackend,
        "paddleocr": PaddleOCRBackend,
    }
    cls = mapping.get(name)
    if not cls:
        return None
    return cls()
