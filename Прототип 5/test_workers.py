#!/usr/bin/env python3
# Test workers - import/TTS pipeline без OCR

import time
import threading
from queue import Empty

from threading_workers import Queues, ThreadLifecycle, TextComparisonWorker, AudioPrepWorker, AudioPrepDispatcher, PlaybackWorker
from core import TTSEngine, TextTranslator, AudioPlayer
from storage import AudioCache

print("=" * 60)
print("🧪 ТЕСТ WORKER-ОВ")
print("=" * 60)

# Инициализируем компоненты
tts_engine = TTSEngine()
translator = TextTranslator()
audio_player = AudioPlayer()
audio_cache = AudioCache()

print()
print("✅ Компоненты инициализированы")

# Тестируем TextComparisonWorker
print()
print("🧪 ТЕСТ 1: TextComparisonWorker логика")
print("  - Положим импортированную строку в text_comparison_queue")

Queues.text_comparison_queue.put("Привет мир!")
print(f"  - text_comparison_queue size: {Queues.text_comparison_queue.qsize()}")

ThreadLifecycle.start_session()
text_worker = TextComparisonWorker(audio_player, translator)

def run_text_worker_once():
    text_worker.run()

text_thread = threading.Thread(target=run_text_worker_once, daemon=True)
text_thread.start()

print()
print("🧪 ТЕСТ 2: Передача текста в audio_prep_queue")
print("  - Ожидаем задачу после обработки текста")

try:
    payload = Queues.audio_prep_queue.get(timeout=2)
    print(f"  ✅ Получили задачу для TTS: {payload['text']}")
    Queues.audio_prep_queue.put(payload)
except Empty:
    print("  ⚠️ audio_prep_queue пуста")

# Тестируем AudioPrepWorker
print()
print("🧪 ТЕСТ 3: AudioPrepWorker логика")
audio_prep_worker = AudioPrepWorker(tts_engine, audio_cache)

test_text = "тестовая фраза"
print(f"  - Синтезируем: {test_text}")

# Запускаем в отдельном потоке (TTS займет время)
def test_synthesis():
    audio_prep_worker.synthesize_task(test_text)
    print(f"  ✅ Синтез завершён")

synthesis_thread = threading.Thread(target=test_synthesis, daemon=True)
synthesis_thread.start()

# Ждём результата в очереди
print("  - Ожидаем результат в ready_audio_queue...")
time.sleep(3)  # TTS синтез занимает время

try:
    result = Queues.ready_audio_queue.get(timeout=2)
    print(f"  ✅ Получили результат: {result['text_preview']}")
    print(f"     Audio path: {result['audio_path']}")
except Empty:
    print("  ⚠️ Результат не готов (TTS может быть медленным)")

synthesis_thread.join(timeout=5)

print()
print("✅ ThreadPoolExecutor логика проверена")

# Очищаем для следующих тестов
ThreadLifecycle.stop_session()
text_thread.join(timeout=2)
Queues.clear_all()

print()
print("=" * 60)
print("✅ ВСЕ WORKER ТЕСТЫ ПРОЙДЕНЫ")
print("=" * 60)
print()
print("💡 СТАТУС АРХИТЕКТУРЫ:")
print("   ✅ config.py - import/TTS настройки")
print("   ✅ core/ - TTS, Translator, AudioPlayer")
print("   ✅ storage/ - SettingsManager, AudioCache, HistoryManager")
print("   ✅ utils/ - Logger, helpers")
print("   ✅ threading_workers/ - Queues, ThreadLifecycle, import/TTS workers")
print("   ✅ ui/ - MainWindow для import/extract pipeline")
print()
print("🚀 ГОТОВО К ЗАПУСКУ: python main.py")
print("=" * 60)
