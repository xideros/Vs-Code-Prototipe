# threading_workers/workers.py - Все рабочие потоки

import os
import time
import re
from queue import Empty
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
        """Исправляет распространённые ошибки OCR только для русского текста"""
        if not text:
            return text

        # Склеиваем переносы строк внутри слова: "ре- зультат" -> "результат".
        text = re.sub(r'(?<=[A-Za-zА-Яа-яЁё])\-\s+(?=[A-Za-zА-Яа-яЁё])', '', text)
        
        # ✅ ПРОВЕРКА: применяем исправления ТОЛЬКО если в тексте есть кириллица
        # Иначе испортим английский текст (Hello → Hellо)
        if not re.search(r'[а-яА-ЯЁё]', text):
            # Только латиница → не применяем исправления
            text = ' '.join(text.split()).strip()  # Только нормализуем пробелы
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
        
        # Нормализуем пробелы
        text = ' '.join(text.split()).strip()
        
        return text
    
    def run(self):
        """Основной цикл OCR worker-а"""
        log("🔄 OCR Worker запущен", level="INFO")
        
        while ThreadLifecycle.is_ocr_running():
            screenshot_path = None
            try:
                # Берём скриншот из очереди
                screenshot_path = Queues.ocr_queue.get(timeout=config.OCR_QUEUE_TIMEOUT)
                
                if not screenshot_path or not os.path.exists(screenshot_path):
                    continue
                
                # Распознаём текст
                text = self.ocr_engine.recognize(screenshot_path)
                
                if text:
                    # 🔴 Быстрый пропуск если текст не изменился
                    if text == self.last_ocr_result:
                        continue
                    self.last_ocr_result = text
                    
                    # === ИСПРАВЛЯЕМ ОШИБКИ OCR ===
                    text = self._fix_text(text)
                    
                    # Переводим если нужно
                    translated_text = self.translator.translate(text)
                    
                    # Отправляем в очередь сравнения
                    Queues.text_comparison_queue.put(translated_text)
                    
                    log(f"📝 OCR: {text_preview(translated_text)}", level="DEBUG")
            
            except Empty:
                continue
            except Exception as e:
                log(f"❌ Ошибка OCR worker: {e}", level="ERROR")
            finally:
                # ✅ УДАЛЯЕМ ВРЕМЕННЫЙ ФАЙЛ
                if screenshot_path and os.path.exists(screenshot_path):
                    try:
                        os.remove(screenshot_path)
                        log(f"🗑️ Удалён скриншот: {os.path.basename(screenshot_path)}", level="DEBUG")
                    except Exception as e:
                        log(f"⚠️ Не удалось удалить скриншот: {e}", level="WARNING")
        
        log("⏹️ OCR Worker завершён", level="INFO")

class TextComparisonWorker:
    """Поток сравнения текста и дедупликации"""

    def __init__(self, audio_player: AudioPlayer | None = None):
        self.audio_player = audio_player
    
    def run(self):
        """Основной цикл text comparison worker-а"""
        log("🔄 TextComparison Worker запущен", level="INFO")
        
        while ThreadLifecycle.is_ocr_running():
            try:
                ru_text = Queues.text_comparison_queue.get(
                    timeout=config.COMPARISON_QUEUE_TIMEOUT
                )
                
                if not ru_text:
                    continue
                
                # Проверяем активность сессии
                if not ThreadLifecycle.is_active():
                    log(f"⏭️ Сессия неактивна, пропускаем", level="DEBUG")
                    continue
                
                # Нормализуем текст
                ru_text_normalized = normalize_text(ru_text)
                
                # ✅ СИНХРОНИЗИРОВАННО: получаем последний озвученный текст
                with ThreadLifecycle._state_lock:
                    last_spoken_normalized = (
                        normalize_text(ThreadLifecycle.last_spoken_text)
                        if ThreadLifecycle.last_spoken_text else None
                    )
                    current_time = time.time()
                    time_since_last = current_time - ThreadLifecycle.last_spoken_text_time
                
                # Проверяем новизну текста
                if (ru_text_normalized != last_spoken_normalized or 
                    time_since_last > config.DUPLICATE_SKIP_TIMEOUT):

                    # Если сейчас проигрывается другой текст, прерываем его сразу.
                    with ThreadLifecycle._playback_lock:
                        current_playback_text = ThreadLifecycle.current_playback_text

                    if current_playback_text:
                        current_playback_normalized = normalize_text(current_playback_text)
                        if current_playback_normalized != ru_text_normalized and self.audio_player:
                            log("⏭️ Новый текст обнаружен, прерываем текущее воспроизведение", level="INFO")
                            self.audio_player.stop()

                    # Могли нажать Stop во время обработки этого текста.
                    if not ThreadLifecycle.is_active():
                        log("⏭️ Сессия остановлена во время обработки, пропускаем текст", level="DEBUG")
                        continue
                    
                    log(f"📝 Новый текст: {text_preview(ru_text)}", level="INFO")
                    
                    # ✅ СИНХРОНИЗИРОВАННО: обновляем состояние
                    with ThreadLifecycle._state_lock:
                        ThreadLifecycle.last_spoken_text = ru_text_normalized
                        ThreadLifecycle.last_spoken_text_time = current_time
                    
                    # Отправляем в очередь подготовки аудио
                    Queues.audio_prep_queue.put(ru_text)
                else:
                    log(f"⏭️ Дубликат пропущен: {text_preview(ru_text)}", level="DEBUG")
            
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
    
    def set_speed(self, speed: float):
        """Установить скорость озвучки (1.0-3.0)"""
        self.current_speed = max(config.TTS_SPEED_MIN, min(speed, config.TTS_SPEED_MAX))
    
    def synthesize_task(self, text: str):
        """Задача синтеза для ThreadPoolExecutor"""
        try:
            original_text = text
            
            # ✅ КОПИРУЕМ СКОРОСТЬ В НАЧАЛЕ (избегаем race condition если UI изменит скорость)
            speed = self.current_speed
            
            try:
                from deep_translator import GoogleTranslator
                from langdetect import detect
                
                # ✅ ОПРЕДЕЛЕНИЕ ЯЗЫКА: используем langdetect
                detected = None
                try:
                    detected = detect(text)
                    log(f"🌐 Определён язык: {detected}", level="DEBUG")
                except Exception as e:
                    log(f"⚠️ Ошибка определения языка: {e}, предполагаем английский", level="WARNING")
                    detected = 'en'
                
                # === ПЕРЕВОДИМ ВСЕ ЯЗЫКИ НА РУССКИЙ ===
                # Никакой язык не пропускается - все озвучиваются на русском
                if detected and detected != 'ru':
                    try:
                        text_translated = GoogleTranslator(source_language=detected, target_language='ru').translate(text)
                        log(f"📖 Переведено для TTS: {detected} → ru", level="DEBUG")
                        text = text_translated  # Используем переведённый текст для TTS
                    except Exception as e:
                        log(f"⚠️ Ошибка перевода Google Translator: {e}, используем оригинальный текст", level="WARNING")
                        # Используем оригинальный текст если перевод не удался
                        pass
                else:
                    # Уже русский или определение предположило русский
                    log(f"📝 Текст на русском, озвучиваем: {text_preview(original_text)}", level="DEBUG")
            except Exception as e:
                log(f"⚠️ Ошибка в блоке трансляции: {e}", level="WARNING")
            
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
                # Отправляем в очередь воспроизведения (оригинальный текст на экран, но аудио на русском)
                Queues.ready_audio_queue.put({
                    'text': original_text,
                    'audio_path': audio_path,
                    'text_preview': text_preview(original_text)
                })
        
        except Exception as e:
            log(f"❌ Ошибка синтеза: {e}", level="ERROR")

class AudioPrepDispatcher:
    """Диспетчер очереди для распределения задач в пул TTS"""
    
    def __init__(self, audio_prep_worker: AudioPrepWorker):
        self.audio_prep_worker = audio_prep_worker
        self.executor = None
    
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
                text_to_synthesize = Queues.audio_prep_queue.get(
                    timeout=0.5
                )
                
                if not text_to_synthesize:
                    continue
                
                # Отправляем в пул потоков
                if self.executor:
                    self.executor.submit(
                        self.audio_prep_worker.synthesize_task,
                        text_to_synthesize
                    )
            
            except Empty:
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
