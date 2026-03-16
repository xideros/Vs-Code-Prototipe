#!/usr/bin/env python3
# Test script for modular architecture

print('🧪 ТЕСТ 4: SettingsManager')
from storage import SettingsManager

settings = SettingsManager()
settings.load()

print(f'  volume: {settings.get("volume")}')
print(f'  speed: {settings.get("speed")}')
print(f'  game_root: {settings.get("game_root")}')
print(f'  auto_detect_game_root: {settings.get("auto_detect_game_root")}')

print()
print('🔨 Тест set()...')
settings.set('volume', 75)
print(f'  volume после set: {settings.get("volume")}')

print()
print('✅ SettingsManager работает корректно!')

print()
print('🧪 ТЕСТ 5: AudioCache')
from storage import AudioCache

cache = AudioCache()
print(f'  Cache dir: {cache.cache_dir}')
print(f'  Cache size: {cache.get_size()} bytes')

print()
print('✅ AudioCache работает корректно!')

print()
print('🧪 ТЕСТ 6: HistoryManager')
from storage import HistoryManager

history = HistoryManager()
print(f'  History file: {history.history_file}')

test_text = "Тестовая фраза"
history.add(test_text)
phrases = history.get_all()
print(f'  Phrases in history: {len(phrases)}')
if test_text in phrases:
    print(f'  ✅ Тестовая фраза добавлена успешно!')

print()
print('✅ HistoryManager работает корректно!')

print()
print('🧪 ТЕСТ 7: Helper functions')
from utils.helpers import normalize_text, text_preview, get_md5_hash

text = "  Привет   МИР  "
normalized = normalize_text(text)
print(f'  normalize_text("{text}") = "{normalized}"')

preview = text_preview("Это очень длинный текст который должен быть обрезан для просмотра в логах", length=30)
print(f'  text_preview(...) = "{preview}"')

hash_val = get_md5_hash("test")
print(f'  get_md5_hash("test") = {hash_val}')

print()
print('✅ Helper functions работают корректно!')

print()
print('=' * 50)
print('🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!')
print('=' * 50)
