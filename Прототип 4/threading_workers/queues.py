# threading_workers/queues.py - Все очереди в одном месте

from queue import Queue
import config

class Queues:
    """Единственное место где определены все очереди"""
    
    # Очередь скриншотов на обработку OCR
    ocr_queue = Queue(maxsize=getattr(config, "OCR_QUEUE_MAXSIZE", 1))
    
    # Очередь текстов для сравнения и дедупликации
    text_comparison_queue = Queue(
        maxsize=getattr(config, "TEXT_COMPARISON_QUEUE_MAXSIZE", 1)
    )
    
    # Очередь текстов для подготовки аудио (TTS)
    audio_prep_queue = Queue()
    
    # Очередь готовых аудио файлов для воспроизведения
    ready_audio_queue = Queue()
    
    @classmethod
    def clear_all(cls):
        """Очистить ВСЕ очереди"""
        while not cls.ocr_queue.empty():
            try:
                cls.ocr_queue.get_nowait()
            except:
                break
        
        while not cls.text_comparison_queue.empty():
            try:
                cls.text_comparison_queue.get_nowait()
            except:
                break
        
        while not cls.audio_prep_queue.empty():
            try:
                cls.audio_prep_queue.get_nowait()
            except:
                break
        
        while not cls.ready_audio_queue.empty():
            try:
                cls.ready_audio_queue.get_nowait()
            except:
                break
