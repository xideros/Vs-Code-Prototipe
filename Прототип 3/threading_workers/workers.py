# threading_workers/workers.py - Все рабочие потоки

import os
import time
import re
import difflib
from queue import Empty, Full
from concurrent.futures import ThreadPoolExecutor

import config

from core import OCREngine, TTSEngine, AudioPlayer, TextTranslator
from storage import AudioCache, HistoryManager
from utils.logger import log
from utils.helpers import normalize_text, text_preview

from .queues import Queues
from .lifecycle import ThreadLifecycle

class OCRWorker:
    """Поток OCR обработки скриншотов"""
    
    def __init__(self, ocr_engine: OCREngine, translator: TextTranslator):
        self.ocr_engine = ocr_engine
        self.translator = translator
        self.screenshot_dir = config.CONFIG_DIR
        self.last_ocr_result = None
    
    def _fix_text(self, text: str) -> str:
        """Исправляет OCR-текст без искажения нерусских языков."""
        if not text:
            return text

        # Склеиваем переносы строк внутри слова: "ре- зультат" -> "результат".
        text = re.sub(r'(?<=[A-Za-zА-Яа-яЁё])\-\s+(?=[A-Za-zА-Яа-яЁё])', '', text)

        # Нормализуем пробелы перед любыми языковыми проверками.
        text = ' '.join(text.split()).strip()

        source_lang = getattr(config, "TRANSLATOR_SOURCE_LANG", "auto")
        contains_cyr = bool(re.search(r'[а-яА-ЯЁё]', text))

        # Русские OCR-фиксы применяем только в явном RU-режиме.
        # В auto режиме они часто искажают смешанные/нерусские строки.
        if source_lang != "ru" or not contains_cyr:
            return text
        
        # === ИСПРАВЛЕНИЯ ЛАТИНИЦЫ НА КИРИЛЛИЦУ ===
        # h→н, o→о, p→р, c→с, y→у, x→х, e→е, a→а, и т.д.
        # ТОЛЬКО если окружены кириллицей (Hello не испортится)
        latin_to_cyrillic = {
            'h': 'н', 'H': 'Н',
            'o': 'о', 'O': 'О',
            'p': 'р', 'P': 'Р',
            'c': 'с', 'C': 'С',
            'y': 'у', 'Y': 'У',
            'x': 'х', 'X': 'Х',
            'e': 'е', 'E': 'Е',
            'a': 'а', 'A': 'А',
            'B': 'В', 'b': 'в',
            'M': 'М', 'T': 'Т',
        }
        
        for latin, cyrillic in latin_to_cyrillic.items():
            # Заменяем латиницу кириллицей ТОЛЬКО если она окружена кириллицей/цифрами
            text = re.sub(f'([а-яА-ЯЁё0-9]){re.escape(latin)}([а-яА-ЯЁё0-9])', 
                         f'\\1{cyrillic}\\2', text)
        
        # === ИСПРАВЛЕНИЯ ОПЕЧАТОК ===
        fixes = {
            r'\bЗННЕТ\b': 'ЗНАЕТ',
            r'\bМЕЕТСЯ\b': 'МЕЖДУ',
            r'\bЖЫВ\b': 'ЖИВ',
        }
        for pattern, repl in fixes.items():
            text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
        
        return text
    
    def run(self):
        """Основной цикл OCR worker-а"""
        log("🔄 OCR Worker запущен", level="INFO")
        
        while ThreadLifecycle.is_ocr_running():
            screenshot_item = None
            try:
                # Берём скриншот из очереди
                screenshot_item = Queues.ocr_queue.get(timeout=config.OCR_QUEUE_TIMEOUT)

                if screenshot_item is None:
                    continue

                if isinstance(screenshot_item, str) and not os.path.exists(screenshot_item):
                    continue
                
                # Распознаём текст
                text = self.ocr_engine.recognize(screenshot_item)
                
                if text:
                    # 🔴 Быстрый пропуск если текст не изменился
                    if text == self.last_ocr_result:
                        continue
                    self.last_ocr_result = text
                    
                    # === ИСПРАВЛЯЕМ ОШИБКИ OCR ===
                    text = self._fix_text(text)
                    
                    # Отправляем в очередь сравнения только последний текст.
                    keep_latest = bool(getattr(config, "TEXT_COMPARISON_KEEP_LATEST", True))
                    if keep_latest:
                        while not Queues.text_comparison_queue.empty():
                            try:
                                Queues.text_comparison_queue.get_nowait()
                            except Empty:
                                break

                    try:
                        Queues.text_comparison_queue.put_nowait(text)
                    except Full:
                        try:
                            Queues.text_comparison_queue.get_nowait()
                        except Empty:
                            pass
                        Queues.text_comparison_queue.put_nowait(text)
                    log(f"📝 OCR: {text_preview(text)}", level="DEBUG")
            
            except Empty:
                continue
            except Exception as e:
                log(f"❌ Ошибка OCR worker: {e}", level="ERROR")
            finally:
                # Удаляем только legacy-файлы, если они попадут в очередь.
                if isinstance(screenshot_item, str) and os.path.exists(screenshot_item):
                    try:
                        os.remove(screenshot_item)
                    except Exception as e:
                        log(f"⚠️ Не удалось удалить скриншот: {e}", level="WARNING")
        
        log("⏹️ OCR Worker завершён", level="INFO")

class TextComparisonWorker:
    """Поток сравнения текста и дедупликации"""

    def __init__(self, audio_player: AudioPlayer | None = None, translator: TextTranslator | None = None):
        self.audio_player = audio_player
        self.translator = translator
        self._candidate_text = ""
        self._candidate_raw_text = ""
        self._candidate_hits = 0

    def _canonical_text(self, text: str) -> str:
        """Привести OCR-текст к форме для устойчивого сравнения."""
        if not text:
            return ""

        s = text.lower().replace("ё", "е")
        s = re.sub(r"@[a-z0-9_.-]+", " ", s)
        s = re.sub(r"\b[\w.-]+\.(?:info|com|net|org|ru)\b", " ", s, flags=re.IGNORECASE)
        s = re.sub(r"[^\w\sа-яА-ЯёЁ]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _is_same_or_similar(self, a: str, b: str) -> bool:
        """Считать строки одинаковыми, если они очень похожи (OCR jitter)."""
        ca = self._canonical_text(a)
        cb = self._canonical_text(b)

        if not ca or not cb:
            return False
        if ca == cb:
            return True

        min_len = int(getattr(config, "TEXT_MIN_COMPARE_LEN", 10))
        if len(ca) >= min_len and len(cb) >= min_len:
            shorter, longer = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
            if shorter in longer:
                return True

        threshold = float(getattr(config, "TEXT_SIMILARITY_THRESHOLD", 0.84))
        ratio = difflib.SequenceMatcher(None, ca, cb).ratio()
        return ratio >= threshold

    def _is_candidate_confirmed(self, ru_text: str) -> tuple[bool, str]:
        """Подтверждение текста по нескольким похожим кадрам подряд."""
        canonical = self._canonical_text(ru_text)
        min_len = int(getattr(config, "TEXT_CONFIRM_MIN_CANONICAL_LEN", 6))
        if len(canonical) < min_len:
            self._candidate_text = ""
            self._candidate_raw_text = ""
            self._candidate_hits = 0
            return False, ""

        if self._candidate_text and self._is_same_or_similar(canonical, self._candidate_text):
            self._candidate_hits += 1
        else:
            self._candidate_text = canonical
            self._candidate_raw_text = ru_text
            self._candidate_hits = 1

        required_hits = int(getattr(config, "TEXT_CONFIRM_FRAMES", 2))
        if self._candidate_hits >= max(1, required_hits):
            confirmed_text = self._candidate_raw_text
            self._candidate_text = ""
            self._candidate_raw_text = ""
            self._candidate_hits = 0
            return True, confirmed_text

        return False, ""

    def _script_ratio_for_lang(self, text: str, lang_code: str) -> float:
        """Доля букв, соответствующих письменности выбранного языка."""
        letters = [ch for ch in text if ch.isalpha()]
        if not letters:
            return 0.0

        if lang_code == "ru":
            matched = sum(1 for ch in letters if ('а' <= ch.lower() <= 'я') or ch in ('ё', 'Ё'))
            return matched / max(1, len(letters))

        if lang_code in {"en", "de", "fr", "es", "it", "pt", "tr"}:
            # Латиница с расширенным диапазоном (акценты и диакритика).
            matched = sum(1 for ch in letters if (
                ('A' <= ch <= 'Z')
                or ('a' <= ch <= 'z')
                or (0x00C0 <= ord(ch) <= 0x024F)
            ))
            return matched / max(1, len(letters))

        if lang_code == "ja":
            matched = sum(1 for ch in letters if (
                (0x3040 <= ord(ch) <= 0x309F)  # Hiragana
                or (0x30A0 <= ord(ch) <= 0x30FF)  # Katakana
                or (0x4E00 <= ord(ch) <= 0x9FFF)  # Kanji
            ))
            return matched / max(1, len(letters))

        if lang_code == "ko":
            matched = sum(1 for ch in letters if (
                (0xAC00 <= ord(ch) <= 0xD7AF)  # Hangul syllables
                or (0x1100 <= ord(ch) <= 0x11FF)  # Jamo
                or (0x3130 <= ord(ch) <= 0x318F)  # Compatibility Jamo
            ))
            return matched / max(1, len(letters))

        if lang_code == "zh-CN":
            matched = sum(1 for ch in letters if (0x4E00 <= ord(ch) <= 0x9FFF))
            return matched / max(1, len(letters))

        return 1.0

    def _is_meaningful_text(self, text: str) -> bool:
        """Отсечь OCR-мусор, который не похож на естественную фразу."""
        canonical = self._canonical_text(text)
        if not canonical:
            return False

        # Для одинаковых языков режем шум по письменности выбранного языка,
        # чтобы корректная реплика не вытеснялась OCR-мусором.
        src_lang = getattr(config, "TRANSLATOR_SOURCE_LANG", "auto")
        dst_lang = getattr(config, "TRANSLATOR_TARGET_LANG", "ru")
        if src_lang != "auto" and src_lang == dst_lang:
            thresholds = getattr(config, "TEXT_SAME_LANG_SCRIPT_RATIO_THRESHOLDS", {})
            default_threshold = float(getattr(config, "TEXT_RU_ONLY_MODE_MIN_CYR_RATIO", 0.72))
            min_script_ratio = float(thresholds.get(src_lang, default_threshold))
            script_ratio = self._script_ratio_for_lang(text, src_lang)
            if script_ratio < min_script_ratio:
                return False

        min_cmp = int(getattr(config, "TEXT_MIN_COMPARE_LEN", 10))
        if len(canonical) < min_cmp:
            return False

        letters = sum(1 for ch in canonical if ch.isalpha())
        min_letters = int(getattr(config, "TEXT_MIN_LETTERS", 8))
        if letters < min_letters:
            return False

        tokens = [t for t in canonical.split() if any(ch.isalpha() for ch in t)]
        if not tokens:
            return False

        min_words = int(getattr(config, "TEXT_MIN_WORDS", 2))
        if len(tokens) >= min_words:
            return True

        single_min_len = int(getattr(config, "TEXT_SINGLE_WORD_MIN_LEN", 12))
        return len(tokens) == 1 and len(tokens[0]) >= single_min_len
    
    def run(self):
        """Основной цикл text comparison worker-а"""
        log("🔄 TextComparison Worker запущен", level="INFO")
        
        while ThreadLifecycle.is_ocr_running():
            try:
                input_text = Queues.text_comparison_queue.get(
                    timeout=config.COMPARISON_QUEUE_TIMEOUT
                )
                
                if not input_text:
                    continue
                
                # Проверяем активность сессии
                if not ThreadLifecycle.is_active():
                    log(f"⏭️ Сессия неактивна, пропускаем", level="DEBUG")
                    continue
                
                # Нормализуем текст
                input_text_normalized = normalize_text(input_text)

                if not self._is_meaningful_text(input_text_normalized):
                    continue

                confirmed, confirmed_text = self._is_candidate_confirmed(input_text_normalized)
                if not confirmed:
                    continue

                output_text = confirmed_text
                if bool(getattr(config, "TRANSLATE_ONLY_CONFIRMED_TEXT", True)) and self.translator:
                    output_text = self.translator.translate(confirmed_text)
                ru_text_normalized = normalize_text(output_text)
                
                # ✅ СИНХРОНИЗИРОВАННО: получаем последний озвученный текст
                with ThreadLifecycle._state_lock:
                    last_spoken_normalized = (
                        normalize_text(ThreadLifecycle.last_spoken_text)
                        if ThreadLifecycle.last_spoken_text else None
                    )
                    current_time = time.time()
                    time_since_last = current_time - ThreadLifecycle.last_spoken_text_time
                
                # Проверяем новизну текста
                is_similar_to_last = self._is_same_or_similar(ru_text_normalized, last_spoken_normalized or "")

                if ((not is_similar_to_last) or 
                    time_since_last > config.DUPLICATE_SKIP_TIMEOUT):

                    # Если сейчас проигрывается другой текст, прерываем его сразу.
                    with ThreadLifecycle._playback_lock:
                        current_playback_text = ThreadLifecycle.current_playback_text

                    if current_playback_text:
                        current_playback_normalized = normalize_text(current_playback_text)
                        if (not self._is_same_or_similar(current_playback_normalized, ru_text_normalized)) and self.audio_player:
                            log("⏭️ Новый текст обнаружен, прерываем текущее воспроизведение", level="INFO")
                            self.audio_player.stop()

                    # Могли нажать Stop во время обработки этого текста.
                    if not ThreadLifecycle.is_active():
                        log("⏭️ Сессия остановлена во время обработки, пропускаем текст", level="DEBUG")
                        continue
                    
                    log(f"📝 Новый текст: {text_preview(output_text)}", level="INFO")
                    
                    # ✅ СИНХРОНИЗИРОВАННО: обновляем состояние
                    with ThreadLifecycle._state_lock:
                        ThreadLifecycle.last_spoken_text = ru_text_normalized
                        ThreadLifecycle.last_spoken_text_time = current_time

                    # Приоритет последнего текста: очищаем устаревшие задания.
                    while not Queues.audio_prep_queue.empty():
                        try:
                            Queues.audio_prep_queue.get_nowait()
                        except Empty:
                            break
                    while not Queues.ready_audio_queue.empty():
                        try:
                            Queues.ready_audio_queue.get_nowait()
                        except Empty:
                            break
                    
                    # Отправляем в очередь подготовки аудио
                    Queues.audio_prep_queue.put({
                        'text': output_text,
                        'queued_at': current_time,
                    })
                else:
                    log(f"⏭️ Дубликат пропущен: {text_preview(output_text)}", level="DEBUG")
            
            except Empty:
                continue
            except Exception as e:
                log(f"❌ Ошибка TextComparison worker: {e}", level="ERROR")
        
        log("⏹️ TextComparison Worker завершён", level="INFO")

class AudioPrepWorker:
    """Работник подготовки аудио в ThreadPoolExecutor"""
    
    def __init__(self, tts_engine: TTSEngine, audio_cache: AudioCache):
        self.tts_engine = tts_engine
        self.audio_cache = audio_cache
        self.current_speed = config.TTS_SPEED_DEFAULT

    def _prepare_text_for_tts(self, text: str) -> str:
        """Очистить OCR-шум и ограничить длину для быстрого TTS."""
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        # Убираем типичный рекламный мусор/артефакты OCR.
        cleaned = re.sub(r"@[A-Za-z0-9_.-]+", " ", cleaned)
        cleaned = re.sub(r"\b[\w.-]+\.(?:info|com|net|org|ru)\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bhttps?://\S+\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        if not cleaned:
            return ""

        # Отбрасываем строки с низкой долей букв (часто это OCR-мусор).
        alpha = sum(1 for ch in cleaned if ch.isalpha())
        alpha_ratio = alpha / max(1, len(cleaned))
        min_ratio = float(getattr(config, "TTS_MIN_ALPHA_RATIO", 0.30))
        if alpha_ratio < min_ratio:
            return ""

        # Для низкой задержки озвучиваем только первую законченную фразу.
        sentence_parts = re.split(r"(?<=[.!?…])\s+", cleaned, maxsplit=1)
        if sentence_parts:
            cleaned = sentence_parts[0].strip() or cleaned

        max_chars = int(getattr(config, "TTS_MAX_TEXT_CHARS", 160))
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars].rsplit(" ", 1)[0].strip() or cleaned[:max_chars]

        return cleaned
    
    def set_speed(self, speed: float):
        """Установить скорость озвучки (1.0-3.0)"""
        self.current_speed = max(config.TTS_SPEED_MIN, min(speed, config.TTS_SPEED_MAX))
    
    def synthesize_task(self, payload):
        """Задача синтеза для ThreadPoolExecutor"""
        try:
            if isinstance(payload, dict):
                original_text = str(payload.get('text', ''))
                queued_at = float(payload.get('queued_at', time.time()))
            else:
                original_text = str(payload)
                queued_at = time.time()

            if not original_text:
                return

            original_normalized = normalize_text(original_text)

            # Снимем актуальный последний текст один раз для проверок stale-drop.
            with ThreadLifecycle._state_lock:
                latest_text = normalize_text(ThreadLifecycle.last_spoken_text or "")

            # Если фраза уже слишком старая, не тратим время на синтез.
            max_age = float(getattr(config, "TTS_DROP_IF_OLDER_THAN_SEC", 2.5))
            if time.time() - queued_at > max_age:
                # Не дропаем, если это все еще самый свежий текст: иначе пользователь
                # увидит "Новый текст" без озвучки.
                if latest_text and original_normalized != latest_text:
                    log(f"⏭️ Пропуск старого текста до TTS: {text_preview(original_text)}", level="DEBUG")
                    return
                log(
                    f"⏱️ Поздний TTS (оставляем последний текст): {text_preview(original_text)}",
                    level="INFO",
                )

            # Если текст уже точно устарел относительно последнего, не тратим время на синтез.
            if latest_text and original_normalized != latest_text:
                log(f"⏭️ Пропуск устаревшего TTS: {text_preview(original_text)}", level="DEBUG")
                return
            
            # ✅ КОПИРУЕМ СКОРОСТЬ В НАЧАЛЕ (избегаем race condition если UI изменит скорость)
            speed = self.current_speed

            # Ускорение: перевод уже выполнен в OCRWorker через TextTranslator,
            # повторная трансляция здесь избыточна и замедляет TTS-пайплайн.
            text = self._prepare_text_for_tts(original_text)
            if not text:
                log(f"⏭️ Пропуск шумного/пустого текста для TTS: {text_preview(original_text)}", level="DEBUG")
                return
            
            # Проверяем кеш
            cached_path = self.audio_cache.get(text)
            if cached_path:
                log(f"💾 Из кеша: {text_preview(original_text)}", level="DEBUG")
                audio_path = cached_path
            else:
                # Синтезируем новое аудио (text теперь на русском или оригинальный)
                # Используем скопированную скорость (чтобы избежать обновления во время синтеза)
                audio_path = self.tts_engine.synthesize(text, speed)
                
                if audio_path:
                    # Сохраняем в кеш
                    self.audio_cache.put(text, audio_path)
            
            if audio_path:
                synthesized_at = time.time()

                # После долгого синтеза фраза могла устареть.
                if synthesized_at - queued_at > max_age:
                    with ThreadLifecycle._state_lock:
                        latest_after_tts = normalize_text(ThreadLifecycle.last_spoken_text or "")
                    if latest_after_tts and original_normalized != latest_after_tts:
                        log(f"⏭️ Пропуск старого аудио после TTS: {text_preview(original_text)}", level="DEBUG")
                        return
                    log(
                        f"⏱️ Поздний аудио-результат (оставляем последний текст): {text_preview(original_text)}",
                        level="INFO",
                    )

                # Отправляем в очередь воспроизведения (оригинальный текст на экран, но аудио на русском)
                Queues.ready_audio_queue.put({
                    'text': original_text,
                    'audio_path': audio_path,
                    'text_preview': text_preview(original_text),
                    'queued_at': queued_at,
                    'synthesized_at': synthesized_at,
                })
        
        except Exception as e:
            log(f"❌ Ошибка синтеза: {e}", level="ERROR")

class AudioPrepDispatcher:
    """Диспетчер очереди для распределения задач в пул TTS"""
    
    def __init__(self, audio_prep_worker: AudioPrepWorker):
        self.audio_prep_worker = audio_prep_worker
        self.executor = None
        self._inflight_future = None
        self._latest_payload = None
    
    def run(self):
        """Основной цикл диспетчера"""
        log("🔄 Audio Prep Dispatcher запущен", level="INFO")
        
        # Создаём пол потоков
        self.executor = ThreadPoolExecutor(
            max_workers=config.THREAD_POOL_MAX_WORKERS,
            thread_name_prefix="TTS-Worker"
        )
        log(f"🔥 ThreadPoolExecutor пул создан: {config.THREAD_POOL_MAX_WORKERS} рабочих", 
            level="INFO")
        
        while ThreadLifecycle.is_ocr_running():
            try:
                payload = Queues.audio_prep_queue.get(timeout=0.5)
                if payload:
                    self._latest_payload = payload

                    # Берём только самое свежее задание из очереди.
                    while not Queues.audio_prep_queue.empty():
                        try:
                            candidate = Queues.audio_prep_queue.get_nowait()
                            if candidate:
                                self._latest_payload = candidate
                        except Empty:
                            break

                if not self.executor or not self._latest_payload:
                    continue

                single_flight = bool(getattr(config, "TTS_SINGLE_FLIGHT", True))
                if single_flight:
                    if self._inflight_future and not self._inflight_future.done():
                        # Идёт синтез: ждём, новые задания уже схлопываются в _latest_payload.
                        continue

                self._inflight_future = self.executor.submit(
                    self.audio_prep_worker.synthesize_task,
                    self._latest_payload,
                )
                self._latest_payload = None
            
            except Empty:
                # Даже без новых задач попробуем отправить latest payload,
                # если предыдущий синтез завершился.
                if self.executor and self._latest_payload:
                    single_flight = bool(getattr(config, "TTS_SINGLE_FLIGHT", True))
                    if single_flight and self._inflight_future and not self._inflight_future.done():
                        continue
                    self._inflight_future = self.executor.submit(
                        self.audio_prep_worker.synthesize_task,
                        self._latest_payload,
                    )
                    self._latest_payload = None
                continue
            except Exception as e:
                log(f"❌ Ошибка диспетчера: {e}", level="ERROR")
        
        # Завершаем пул
        if self.executor:
            log("🛑 Завершаем ThreadPoolExecutor...", level="INFO")
            self.executor.shutdown(wait=True)
            self.executor = None
        
        log("⏹️ Audio Prep Dispatcher завершён", level="INFO")

class PlaybackWorker:
    """Поток воспроизведения аудио"""
    
    def __init__(self, audio_player: AudioPlayer):
        self.audio_player = audio_player
    
    def run(self):
        """Основной цикл playback worker-а"""
        log("🔄 Playback Worker запущен", level="INFO")
        
        while ThreadLifecycle.is_ocr_running():
            try:
                audio_dict = Queues.ready_audio_queue.get(
                    timeout=config.PLAYBACK_QUEUE_TIMEOUT
                )
                
                if not audio_dict:
                    continue

                queued_at = float(audio_dict.get('queued_at', time.time()))
                max_age = float(getattr(config, "PLAYBACK_DROP_IF_OLDER_THAN_SEC", 3.2))
                if time.time() - queued_at > max_age:
                    # Не теряем фразу, если это все еще актуальный последний текст.
                    candidate_text = normalize_text(str(audio_dict.get('text', '')))
                    with ThreadLifecycle._state_lock:
                        latest_for_playback = normalize_text(ThreadLifecycle.last_spoken_text or "")
                    if latest_for_playback and candidate_text != latest_for_playback:
                        log("⏭️ Пропуск устаревшего аудио перед воспроизведением", level="DEBUG")
                        continue
                    log("⏱️ Позднее аудио перед воспроизведением: оставляем как актуальное", level="INFO")
                
                audio_text = audio_dict['text'].strip()
                
                # ✅ СИНХРОНИЗИРОВАННО: проверяем паузу
                with ThreadLifecycle._state_lock:
                    if ThreadLifecycle.is_paused:
                        log(f"⏸️ На паузе, откладываем: {audio_dict['text_preview']}", 
                            level="DEBUG")
                        Queues.ready_audio_queue.put(audio_dict)
                        time.sleep(0.1)
                        continue
                
                # ✅ СИНХРОНИЗИРОВАННО: получаем последний озвученный текст
                with ThreadLifecycle._state_lock:
                    last_spoken_normalized = (
                        normalize_text(ThreadLifecycle.last_spoken_text)
                        if ThreadLifecycle.last_spoken_text else ""
                    )
                audio_text_normalized = normalize_text(audio_text)
                
                if (last_spoken_normalized and 
                    last_spoken_normalized != audio_text_normalized):
                    log(f"🛑 Текст изменился, пропускаем устаревшее аудио", 
                        level="DEBUG")
                    continue
                
                # ✅ СИНХРОНИЗИРОВАННО: устанавливаем текущий текст воспроизведения
                with ThreadLifecycle._playback_lock:
                    ThreadLifecycle.current_playback_text = audio_text
                
                try:
                    # Воспроизводим аудио
                    synthesized_at = float(audio_dict.get('synthesized_at', queued_at))
                    now = time.time()
                    prep_delay = max(0.0, synthesized_at - queued_at)
                    total_delay = max(0.0, now - queued_at)

                    if total_delay > 2.0:
                        log(
                            f"⏱️ Задержка до воспроизведения: prep={prep_delay:.2f}s total={total_delay:.2f}s",
                            level="INFO",
                        )

                    log(f"▶️ Воспроизведение: {audio_dict['text_preview']}", level="INFO")
                    self.audio_player.play(audio_dict['audio_path'], blocking=True)
                finally:
                    # Очищаем текст воспроизведения в любом случае
                    with ThreadLifecycle._playback_lock:
                        ThreadLifecycle.current_playback_text = None
            
            except Empty:
                continue
            except Exception as e:
                log(f"❌ Ошибка Playback worker: {e}", level="ERROR")
        
        log("⏹️ Playback Worker завершён", level="INFO")
