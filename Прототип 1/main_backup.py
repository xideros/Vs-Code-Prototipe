# main.py — ассистент с системным треем, ползунками и умной охраной от повторов

import sys
import os
import threading
import time
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor
from tkinter import Tk, Button, Label, Scale, IntVar, messagebox, Frame
import pystray
from PIL import Image, ImageDraw
import cv2
import numpy as np
import mss
from PIL import Image as PilImage
from deep_translator import GoogleTranslator
import pytesseract
from PIL import Image as PILImage
import easyocr
import re
import pyautogui
import pygame
import warnings
import edge_tts
import asyncio
import subprocess

try:
    # Ищем Tesseract в типичных местах
    possible_paths = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        r'C:\Users\%s\AppData\Local\Tesseract-OCR\tesseract.exe' % os.getenv('USERNAME'),
    ]
    
    found_path = None
    for path in possible_paths:
        if os.path.exists(path):
            found_path = path
            break
    
    if found_path:
        pytesseract.pytesseract.pytesseract_cmd = found_path
        USE_TESSERACT = True
        print(f"🚀 Tesseract найден: {found_path}")
    else:
        # Пробуем найти через систему
        result = subprocess.run(['where', 'tesseract.exe'], capture_output=True, text=True)
        if result.returncode == 0:
            pytesseract.pytesseract.pytesseract_cmd = result.stdout.strip()
            USE_TESSERACT = True
            print(f"🚀 Tesseract найден в PATH: {result.stdout.strip()}")
        else:
            USE_TESSERACT = False
            print("⚠️ Tesseract не найден в стандартных местах, будет использоваться EasyOCR")
except Exception as e:
    USE_TESSERACT = False
    print(f"⚠️ Ошибка инициализации Tesseract: {e}")

# Подавляем warning'и PyTorch
warnings.filterwarnings('ignore', category=UserWarning)

CONFIG_FILE = "area_config.txt"
HISTORY_FILE = "history.txt"

settings = {
    'volume': 50,
    'rate': 10,  # 1.0x (диапазон 10-30 = 1.0x-3.0x)
}
history_phrases = set()
history_lock = threading.Lock()  # Синхронизация для history_phrases
current_audio_path = None  # Для блокировки наложений
audio_lock = threading.Lock()  # Блок для озвучки
play_lock = threading.Lock()  # Блокировка для очереди воспроизведения
is_playing = False  # Флаг текущего воспроизведения
previous_text = None  # Последний озвученный текст
current_playback_text = None  # ✅ Текст, который СЕЙЧАС воспроизводится (для прерывания при смене)
previous_screenshot_mtime = None  # Время модификации предыдущего скриншота
current_playback_channel = None  # Текущий канал воспроизведения pygame
last_spoken_text_time = 0  # Время последней озвучки
last_spoken_text = None  # Последний озвученный текст (для защиты от дубликатов)
ocr_session_active = False  # ✅ Флаг активной сессии OCR (для сброса состояния при START)

# === АСИНХРОННЫЙ OCR ===
ocr_queue = Queue()  # Очередь скриншотов на обработку
text_comparison_queue = Queue()  # ✅ Очередь текстов для сравнения
audio_prep_queue = Queue()  # ✅ Очередь для подготовки аудио
ready_audio_queue = Queue()  # ✅ Очередь готовых аудио файлов
ocr_running = False  # Флаг работы OCR потока (начинается как False, запускается по кнопке)
background_thread = None  # Ссылка на поток фонового цикла
text_comparison_thread = None  # ✅ Поток сравнения текса
audio_prep_executor = None  # ✅ ThreadPoolExecutor пул для параллельного TTS (10 потоков)
audio_prep_dispatcher_t = None  # ✅ Поток-диспетчер для распределения задач в пулк
playback_thread = None  # ✅ Поток воспроизведения
pending_text = None  # Текст, ожидающий озвучки
icon = None  # Глобальная переменная для трея
main_window = None  # Главное окно приложения

# Кэш для быстрого распознавания и перевода
ocr_reader = None  # OCR Reader инициализируется один раз
translation_cache = {}  # Кэш переводов {original_text: translated_text}
audio_cache = {}  # Кэш аудио файлов {text: audio_path}
last_ocr_result = None  # Кэш последнего результата OCR для пропуска дубликатов
last_screenshot_in_queue = None  # Последний скриншот в очереди (для дебаунсинга)
last_screenshot_size = 0  # Размер последнего скриншота

# === УПРАВЛЕНИЕ ПАУЗОЙ ===
is_paused = False  # Флаг паузы (если True - не озвучиваем новый текст)
cleanup_done = False  # Флаг чтобы cleanup() вызвалась только один раз
is_speaking = False  # 🔊 Флаг текущей озвучки (блокирует перекрытие)
tts_state_lock = threading.Lock()  # Синхронизация старта/завершения TTS

# Инициализируем pygame.mixer
pygame.mixer.init()

def cleanup():
    """Корректное завершение всех ресурсов"""
    global ocr_running, icon, cleanup_done, audio_prep_executor

    # Защита от двойного вызова (on_closing + atexit)
    if cleanup_done:
        return
    cleanup_done = True
    
    print("\n🛑 Завершение приложения...")
    
    try:
        # 1️⃣ Останавливаем OCR поток
        ocr_running = False
        time.sleep(0.3)
        
        # 2️⃣ Останавливаем воспроизведение
        stop_current_playback()
        
        # 3️⃣ Завершаем ThreadPoolExecutor пул TTS если активен
        try:
            if audio_prep_executor:
                print("🛑 Завершаем ThreadPoolExecutor...")
                audio_prep_executor.shutdown(wait=True)
                print("✅ ThreadPoolExecutor закрыт")
        except Exception as e:
            print(f"⚠️ Ошибка при завершении пула: {e}")
        
        # 4️⃣ Завершаем pygame
        try:
            pygame.mixer.stop()
            pygame.mixer.quit()
        except:
            pass
        
        # 5️⃣ Закрываем трей-иконку если она есть
        try:
            if icon is not None:
                icon.stop()
        except:
            pass
        
        # 6️⃣ Очищаем временные файлы
        for f in ["screenshot.png"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass
        
        print("✅ Приложение закрыто")
    except Exception as e:
        print(f"⚠️ Ошибка при завершении: {e}")

import atexit
atexit.register(cleanup)

def draw_icon(color="green"):
    width, height = 64, 64
    image = Image.new('RGB', (width, height), color='black')
    dc = ImageDraw.Draw(image)
    dc.ellipse([(10, 10), (54, 54)], fill=color, outline="white", width=2)
    return image

def show_settings():
    """Главное окно приложения с управлением и настройками"""
    global is_paused, ocr_running, background_thread, main_window
    
    main_window = Tk()
    main_window.title("🎮 Игровой ассистент")
    main_window.geometry("550x800+400+100")
    main_window.resizable(True, True)
    main_window.minsize(500, 750)
    main_window.attributes('-topmost', True)  # Окно всегда на переднем плане
    main_window.after(100, lambda: main_window.attributes('-topmost', False))  # Отпустить после показа
    
    # === ГРОМКОСТЬ ===
    Label(main_window, text="Громкость озвучки:", font=("Arial", 12, "bold")).pack(pady=(15, 5))
    volume_var = IntVar(value=settings['volume'])
    Scale(main_window, from_=0, to=100, orient='horizontal', variable=volume_var,
          command=lambda val: settings.update({'volume': int(val)}), 
          bg="#e0e0e0", fg="#333").pack(fill='x', padx=30, pady=(0, 10))
    
    # === СКОРОСТЬ РЕЧИ ===
    Label(main_window, text="Скорость речи:", font=("Arial", 12, "bold")).pack(pady=(15, 5))
    rate_var = IntVar(value=settings['rate'])
    speed_label = Label(main_window, text="1.0x", font=("Arial", 14, "bold"), fg="#0066cc")
    speed_label.pack(pady=(0, 5))
    
    def on_rate_change(val):
        settings.update({'rate': int(val)})
        multiplier = int(val) / 10.0
        speed_label.config(text=f"{multiplier:.1f}x")
    
    Scale(main_window, from_=10, to=30, orient='horizontal', variable=rate_var,
          command=on_rate_change, 
          bg="#e0e0e0", fg="#333").pack(fill='x', padx=30, pady=(0, 20))
    
    # === КНОПКИ УПРАВЛЕНИЯ ВОСПРОИЗВЕДЕНИЕМ ===
    Label(main_window, text="Управление озвучкой:", font=("Arial", 11, "bold")).pack(pady=(15, 5))
    
    playback_frame = Frame(main_window)
    playback_frame.pack(pady=5)
    
    def on_pause():
        global is_paused
        is_paused = True
        # Ставим на паузу (сохраняется позиция воспроизведения!)
        if current_playback_channel is not None:
            try:
                current_playback_channel.pause()
                print("⏸️ Озвучка приостановлена (позиция сохранена)")
            except:
                pass
        pause_btn.config(state='disabled')
        resume_btn.config(state='normal')
        status_label.config(text="⏸️ Пауза (нажми Старт для возобновления)", fg="orange")
    
    def on_resume():
        global is_paused, last_spoken_text, last_spoken_text_time
        is_paused = False
        # Возобновляем воспроизведение с позиции паузы
        if current_playback_channel is not None:
            try:
                current_playback_channel.unpause()
                print("▶️ Озвучка возобновлена со слова паузы")
            except:
                pass
        pause_btn.config(state='normal')
        resume_btn.config(state='disabled')
        status_label.config(text="▶️ Озвучка активна", fg="green")
    
    pause_btn = Button(playback_frame, text="⏸️ Пауза", command=on_pause,
                      bg="#ffcccc", font=("Arial", 10), padx=12, pady=8, state='disabled')
    pause_btn.pack(side='left', padx=3)
    
    resume_btn = Button(playback_frame, text="▶️ Старт", command=on_resume,
                       bg="#ccffcc", font=("Arial", 10), padx=12, pady=8, state='disabled')
    resume_btn.pack(side='left', padx=3)
    
    status_label = Label(main_window, text="⏹️ Неактивно", font=("Arial", 10), fg="gray")
    status_label.pack(pady=5)
    
    # === КНОПКИ ЗАПУСКА/ОСТАНОВКИ РАБОТЫ ===
    Label(main_window, text="Управление работой:", font=("Arial", 11, "bold")).pack(pady=(15, 5))
    
    work_frame = Frame(main_window)
    work_frame.pack(pady=5)
    
    def reset_ocr_state():
        """✅ Полный сброс состояния озвучки между START/STOP циклами"""
        global last_spoken_text, last_spoken_text_time, previous_text
        global current_playback_text, is_playing, current_playback_channel, pending_text
        global ocr_session_active
        
        print("🔄 Сброс состояния озвучки и синхронизации...")
        
        # Очищаем все переменные состояния
        last_spoken_text = None
        last_spoken_text_time = 0.0
        previous_text = None
        current_playback_text = None
        pending_text = None
        is_playing = False
        ocr_session_active = False  # Сбрасываем флаг активности
        
        # Останавливаем текущее воспроизведение
        if current_playback_channel is not None:
            try:
                current_playback_channel.stop()
            except:
                pass
            current_playback_channel = None
        
        print("✅ Состояние полностью очищено")
    
    def on_start_work():
        global ocr_running, background_thread, text_comparison_thread, audio_prep_executor
        global playback_thread, audio_prep_dispatcher_t, is_paused, ocr_session_active
        if not ocr_running:
            # ✅ КРИТИЧНО: Полный сброс состояния перед запуском
            reset_ocr_state()
            
            ocr_running = True
            is_paused = False
            ocr_session_active = True  # ✅ КРИТИЧНО: Устанавливаем ДО запуска потоков!
            
            # Инициализируем регион если нужно
            if not os.path.exists(CONFIG_FILE):
                select_area_with_gui()
            
            # Загружаем историю
            load_history()
            
            # ✅ ЗАПУСКАЕМ ВСЕ КОМПОНЕНТЫ В ПАРАЛЛЕЛЬ (ThreadPoolExecutor + потоки)
            # 1️⃣ Фоновый цикл для скриншотов + OCR
            background_thread = threading.Thread(target=background_loop, daemon=True)
            background_thread.start()
            
            # 2️⃣ Поток сравнения текста и защиты от дубликатов
            text_comparison_thread = threading.Thread(target=text_comparison_thread_func, daemon=True)
            text_comparison_thread.start()
            
            # 3️⃣ ThreadPoolExecutor пул + диспетчер для параллельного TTS (8-12 потоков)
            audio_prep_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="TTS-Worker")
            audio_prep_dispatcher_t = threading.Thread(target=audio_prep_dispatcher_thread, daemon=True, name="TTS-Dispatcher")
            audio_prep_dispatcher_t.start()
            print(f"🔥 ThreadPoolExecutor пул создан: 10 рабочих потоков для TTS")
            
            # 4️⃣ Поток воспроизведения аудио из готовой очереди
            playback_thread = threading.Thread(target=playback_thread_func, daemon=True)
            playback_thread.start()
            
            start_btn.config(state='disabled')
            stop_btn.config(state='normal')
            work_status_label.config(text="✅ Работа активна", fg="green")
            pause_btn.config(state='normal')
            resume_btn.config(state='disabled')
            print("✅ Работа начата (4 компоненты активны: фон+OCR, сравнение, TTS-пул, воспроизведение)")
    
    def on_stop_work():
        global ocr_running, is_paused, playback_thread, audio_prep_executor
        ocr_running = False
        is_paused = False
        
        # ✅ КРИТИЧНО: Очищаем всё состояние перед остановкой
        reset_ocr_state()
        
        # 🔴 Очищаем ВСЕ очереди чтобы все потоки вышли!
        # Очередь OCR
        while not ocr_queue.empty():
            try:
                ocr_queue.get_nowait()
            except:
                break
        
        # Очередь сравнения текста
        while not text_comparison_queue.empty():
            try:
                text_comparison_queue.get_nowait()
            except:
                break
        
        # Очередь подготовки аудио
        while not audio_prep_queue.empty():
            try:
                audio_prep_queue.get_nowait()
            except:
                break
        
        # Очередь готового аудио
        while not ready_audio_queue.empty():
            try:
                ready_audio_queue.get_nowait()
            except:
                break
        
        # ✅ Завершаем ThreadPoolExecutor
        if audio_prep_executor:
            print("🛑 Завершаем ThreadPoolExecutor...")
            audio_prep_executor.shutdown(wait=True)
            audio_prep_executor = None
            print("✅ ThreadPoolExecutor закрыт")
        
        time.sleep(0.3)  # Даем всем потокам время выйти
        
        stop_current_playback()
        start_btn.config(state='normal')
        stop_btn.config(state='disabled')
        pause_btn.config(state='disabled')
        resume_btn.config(state='disabled')
        print("⛔ Работа остановлена (все потоки + пул очищены)")
        work_status_label.config(text="⏹️ Работа остановлена", fg="red")
        status_label.config(text="⏹️ Озвучка остановлена", fg="red")
    
    start_btn = Button(work_frame, text="▶️ Начать", command=on_start_work,
                      bg="#90EE90", font=("Arial", 11, "bold"), padx=15, pady=8)
    start_btn.pack(side='left', padx=3)
    
    stop_btn = Button(work_frame, text="⏹️ Стоп", command=on_stop_work,
                     bg="#FFB6C6", font=("Arial", 11, "bold"), padx=15, pady=8, state='disabled')
    stop_btn.pack(side='left', padx=3)
    
    work_status_label = Label(main_window, text="⏹️ Работа остановлена", font=("Arial", 10), fg="red")
    work_status_label.pack(pady=5)
    
    # === КНОПКА ОБНОВИТЬ ОБЛАСТЬ ===
    def on_update_region():
        threading.Thread(target=select_area_with_gui, daemon=True).start()
    
    Button(main_window, text="🎯 Обновить область субтитров", command=on_update_region,
           bg="#cceeff", font=("Arial", 11), padx=15, pady=12).pack(pady=15, fill='x', padx=15)
    
    # === ОБРАБОТКА ЗАКРЫТИЯ ОКНА ===
    def on_closing():
        global ocr_running
        ocr_running = False
        time.sleep(0.2)
        cleanup()
        main_window.destroy()
        sys.exit(0)
    
    main_window.protocol("WM_DELETE_WINDOW", on_closing)
    
    main_window.mainloop()

def select_area_with_gui():
    """Показывает окно для выделения области"""
    screen = pyautogui.screenshot()
    frame = np.array(screen)
    
    win_name = "Выделите область субтитров (нажмите q или крестик)"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_name, 1000, 600)
    cv2.imshow(win_name, frame)

    ref_point = []
    drawing = False

    def on_click(event, x, y, flags, param):
        nonlocal ref_point, drawing
        if event == cv2.EVENT_LBUTTONDOWN:
            ref_point = [(x, y)]
            drawing = True
        elif event == cv2.EVENT_MOUSEMOVE:
            if drawing:
                img_copy = frame.copy()
                cv2.rectangle(img_copy, ref_point[0], (x, y), (0, 255, 0), 3)
                cv2.imshow(win_name, img_copy)
        elif event == cv2.EVENT_LBUTTONUP:
            ref_point.append((x, y))
            drawing = False
            x1, y1 = ref_point[0]
            x2, y2 = ref_point[1]
            min_x, min_y = min(x1, x2), min(y1, y2)
            width, height = abs(x2-x1), abs(y1-y2)
            
            with open(CONFIG_FILE, "w") as f:
                f.write(f"{min_x},{min_y},{width},{height}")
            print(f"✅ Координаты сохранены: ({min(x1,x2)}, {min(y1,y2)}, {abs(x2-x1)}x{abs(y1-y2)})")
            
            cv2.destroyAllWindows()
    
    cv2.setMouseCallback(win_name, on_click)

    while True:
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or cv2.getWindowProperty(win_name, cv2.WND_PROP_VISIBLE) < 1:
            break
    
    cv2.destroyAllWindows()

def load_history():
    global history_phrases
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                with history_lock:
                    history_phrases = set(line.strip() for line in f.readlines())
        except Exception as e:
            print(f"⚠️ Ошибка загрузки истории: {e}")

def save_history(text):
    try:
        with history_lock:
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(text + "\n")
    except Exception as e:
        print(f"⚠️ Ошибка сохранения истории: {e}")

def init_ocr():
    """Инициализирует OCR (Tesseract или EasyOCR)"""
    global ocr_reader
    if not USE_TESSERACT:
        print("🚀 Инициализация EasyOCR (fallback)...")
        ocr_reader = easyocr.Reader(['en', 'ru'], gpu=False)
        print("✅ EasyOCR готов (0.5-2сек на скриншот)")

# === УПРАВЛЕНИЕ ОЧЕРЕДЬЮ ВОСПРОИЗВЕДЕНИЯ ===
def stop_current_playback():
    """Останавливает текущее воспроизведение"""
    global current_playback_channel, is_playing, current_playback_text
    
    if current_playback_channel is not None:
        try:
            current_playback_channel.stop()
            print("⏹️ Предыдущая озвучка прервана")
        except Exception as e:
            print(f"⚠️ Ошибка при остановке: {e}")
    
    is_playing = False
    current_playback_channel = None
    current_playback_text = None

def play_audio_file_with_interrupt_check(audio_path, text_preview, expected_text):
    """✅ Воспроизводит аудио файл с проверкой смены текста на экране"""
    global is_playing, current_audio_path, current_playback_channel, current_playback_text
    global last_spoken_text
    
    try:
        if not os.path.exists(audio_path):
            print(f"⚠️ Файл аудио не найден: {audio_path}")
            return
            
        is_playing = True
        with audio_lock:
            current_audio_path = audio_path
        
        # Загружаем аудио через pygame
        sound = pygame.mixer.Sound(audio_path)
        
        # === ПРИМЕНЯЕМ ГРОМКОСТЬ ===
        volume = settings['volume'] / 100.0  # Конвертируем 0-100 в 0.0-1.0
        sound.set_volume(volume)
        
        # Получаем длительность
        duration = sound.get_length()
        print(f"⏱️ Длительность: {duration:.1f} сек")
        
        # Воспроизводим
        current_playback_channel = pygame.mixer.Channel(0)
        current_playback_channel.play(sound)
        print(f"🔊 Озвучено: {text_preview}")
        
        # ⏱️ Ждём завершения с ПРОВЕРКОЙ смены текста
        check_interval = 0.2  # Проверяем каждые 200ms
        while is_playing and current_playback_channel is not None:
            if current_playback_channel.get_busy():
                # ✅ КРИТИЧНО: Проверяем, не изменился ли текст НА ЭКРАНЕ
                last_spoken_normalized = ' '.join(last_spoken_text.split()).strip() if last_spoken_text else ""
                expected_normalized = ' '.join(expected_text.split()).strip()
                
                if last_spoken_normalized and last_spoken_normalized != expected_normalized:
                    print(f"🔄 СМЕНА ТЕКСТА во время воспроизведения!")
                    print(f"   Было озвучивать: '{expected_normalized[:40]}'")
                    print(f"   Теперь нужно: '{last_spoken_normalized[:40]}'")
                    print(f"🛑 Прерываем текущую озвучку")
                    stop_current_playback()
                    return  # Выходим, новый текст будет озвучен из очереди
                
                time.sleep(check_interval)
            else:
                break
            
    except Exception as e:
        print(f"❌ Ошибка воспроизведения: {e}")
        import traceback
        traceback.print_exc()
    finally:
        is_playing = False
        current_playback_text = None

def play_audio_file(audio_path, text_preview):
    """Воспроизводит аудио файл с использованием pygame и управляет флагом (без проверки смены)"""
    global is_playing, current_audio_path, current_playback_channel, pending_text
    
    try:
        if not os.path.exists(audio_path):
            print(f"⚠️ Файл аудио не найден: {audio_path}")
            return
            
        is_playing = True
        with audio_lock:
            current_audio_path = audio_path
        
        # Загружаем аудио через pygame
        sound = pygame.mixer.Sound(audio_path)
        
        # === ПРИМЕНЯЕМ ГРОМКОСТЬ ===
        volume = settings['volume'] / 100.0  # Конвертируем 0-100 в 0.0-1.0
        sound.set_volume(volume)
        
        # Получаем длительность
        duration = sound.get_length()
        print(f"⏱️ Длительность: {duration:.1f} сек")
        
        # Воспроизводим
        current_playback_channel = pygame.mixer.Channel(0)
        current_playback_channel.play(sound)
        print(f"🔊 Озвучено: {text_preview}")
        
        # Ждём завершения (с проверкой на None)
        while is_playing and current_playback_channel is not None:
            if current_playback_channel.get_busy():
                time.sleep(0.1)
            else:
                break
            
    except Exception as e:
        print(f"❌ Ошибка воспроизведения: {e}")
    finally:
        is_playing = False
        pending_text = None
        try:
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception as e:
            print(f"⚠️ Не удалось удалить {audio_path}: {e}")

def speak_text(text):
    """Озвучивает текст с использованием Edge TTS (быстрый локальный синтез)"""
    global current_audio_path, pending_text, is_playing, is_paused, is_speaking, previous_text
    
    print(f"🗣️ speak_text() вызвана: '{text[:40]}'")  # ✅ Диагностика
    
    # Если пауза включена - не озвучиваем
    if is_paused:
        print(f"⏸️ Озвучка на паузе, пропускаем: {text[:30]}")
        return
    
    if not text or len(text) < 2:
        return
    
    # 🔴 НОВЫЙ ТЕКСТ ОБНАРУЖЕН — прерываем текущую озвучку!
    if previous_text is not None and previous_text != text:
        prev_text_preview = previous_text[:40] if previous_text else "нет"
        print(f"🔄 Смена текста: '{prev_text_preview}' → '{text[:40]}'")
        # Немедленно останавливаем текущее воспроизведение
        stop_current_playback()
        # Сбрасываем флаг озвучки более безопасно
        with tts_state_lock:
            is_speaking = False
        time.sleep(0.05)  # Микропауза для полной очистки
    
    # Блокируем гонку: проверка и установка флага в одном атомарном блоке.
    with tts_state_lock:
        if is_speaking:
            print(f"🔊 Уже идет озвучка, пропускаем: {text[:30]}")
            return
        is_speaking = True
        print(f"✅ Установили is_speaking=True для: '{text[:40]}'")  # ✅ Диагностика
    
    # Ставим pending текст и запускаем озвучку
    pending_text = text
    previous_text = text  # ✅ Обновляем текущий озвучиваемый текст
    time.sleep(0.1)  # Небольшая задержка для чистого переключения
    
    try:
        import tempfile
        
        # Создаем временный файл для MP3
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, prefix="voice_") as f:
            audio_path = f.name
        
        print(f"🚀 Запускаем TTS поток для: '{text[:40]}'")  # ✅ Диагностика
        # Используем Edge TTS асинхронно в отдельном потоке
        threading.Thread(
            target=generate_and_play_audio,
            args=(text, audio_path, text[:50]),
            daemon=True
        ).start()
        
    except Exception as e:
        print(f"❌ Ошибка озвучки: {e}")
        pending_text = None
        with tts_state_lock:
            is_speaking = False

def generate_and_play_audio(text, audio_path, text_preview):
    """Генерирует аудио через Edge TTS и воспроизводит"""
    global pending_text, is_speaking
    
    print(f"🎙️ generate_and_play_audio() вход: '{text_preview}'")  # ✅ Диагностика
    
    try:
        # === ПРИМЕНЯЕМ СКОРОСТЬ РЕЧИ ===
        # Конвертируем 10-30 (1.0x-3.0x) в Edge TTS формат (-100% до +100%)
        multiplier = settings['rate'] / 10.0  # 1.0 - 3.0х
        rate_percent = (multiplier - 1) * 100  # 0% для 1x, +100% для 2x, +200% для 3x
        rate_str = f"{rate_percent:+.0f}%"  # "+50%" или "-50%" формат
        
        print(f"🎵 Edge TTS синтез: скорость {rate_str}")  # ✅ Диагностика
        # Создаём синтезатор Edge TTS со скоростью
        communicate = edge_tts.Communicate(text, voice="ru-RU-DmitryNeural", rate=rate_str)
        
        # Сохраняем в файл асинхронно в синхронном контексте
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(communicate.save(audio_path))
        loop.close()
        
        print(f"✅ Аудио сгенерировано (Edge TTS, скорость: {rate_str})")
        
        # Теперь воспроизводим
        play_audio_file(audio_path, text_preview)
    except Exception as e:
        print(f"❌ Ошибка синтеза Edge TTS: {e}")
        import traceback
        traceback.print_exc()  # ✅ Полная трассировка ошибки
        pending_text = None
    finally:
        with tts_state_lock:
            is_speaking = False  # 🔊 Озвучка завершена
            print(f"✅ Установили is_speaking=False")  # ✅ Диагностика

def playback_thread_func():
    """✅ Поток воспроизведения аудио — получает готовое аудио из очереди и воспроизводит"""
    global ocr_running, is_playing, current_audio_path, pending_text, current_playback_text
    global last_spoken_text
    
    while ocr_running:
        try:
            audio_dict = ready_audio_queue.get(timeout=0.5)
            if not audio_dict:
                continue
            
            audio_text = audio_dict['text'].strip()
            print(f"▶️ Воспроизведение (playback): '{audio_dict['text_preview']}'")
            
            try:
                # Проверяем паузу
                if is_paused:
                    print(f"⏸️ Воспроизведение на паузе, откладываем: {audio_dict['text_preview']}")
                    # Возвращаем обратно в очередь для повторной попытки
                    ready_audio_queue.put(audio_dict)
                    time.sleep(0.1)
                    continue
                
                # 🔴 КРИТИЧНО: Проверяем, не изменился ли текст на экране ДО начала воспроизведения
                last_spoken_normalized = ' '.join(last_spoken_text.split()).strip() if last_spoken_text else ""
                audio_text_normalized = ' '.join(audio_text.split()).strip()
                
                if last_spoken_normalized and last_spoken_normalized != audio_text_normalized:
                    print(f"🛑 Текст изменился ДО начала playback! OCR: '{last_spoken_normalized[:40]}' vs Аудио: '{audio_text_normalized[:40]}'")
                    print(f"⏭️ Пропускаем устаревшее аудио, берём новое")
                    continue
                
                # Сохраняем текст текущего воспроизведения
                current_playback_text = audio_text
                
                # Воспроизводим аудио файл с ОТСЛЕЖИВАНИЕМ смены текста
                play_audio_file_with_interrupt_check(
                    audio_dict['audio_path'], 
                    audio_dict['text_preview'],
                    audio_text  # Передаём текст для проверки смены
                )
                
                # После завершения воспроизведения
                current_playback_text = None
                
            except Exception as e:
                print(f"❌ Ошибка воспроизведения: {e}")
                import traceback
                traceback.print_exc()
                current_playback_text = None
        
        except Empty:
            continue
        except Exception as e:
            print(f"⚠️ Ошибка в потоке воспроизведения: {e}")
            import traceback
            traceback.print_exc()

def text_comparison_thread_func():
    """✅ Поток сравнения текста — проверяет новизну текста и отправляет в очередь подготовки аудио"""
    global ocr_running, last_spoken_text, last_spoken_text_time, previous_text, ocr_session_active
    
    while ocr_running:
        try:
            ru_text = text_comparison_queue.get(timeout=0.5)
            if not ru_text:
                continue
            
            # ✅ Убеждаемся что мы в активной сессии
            if not ocr_session_active:
                print(f"⏭️ Сессия неактивна! (ocr_session_active={ocr_session_active}), пропускаем: {ru_text[:40]}")
                continue
            
            # Нормализуем текст
            ru_text_normalized = ' '.join(ru_text.split())
            last_spoken_text_normalized = ' '.join(last_spoken_text.split()) if last_spoken_text else None
            
            current_time = time.time()
            time_since_last_speak = current_time - last_spoken_text_time
            
            # Проверяем новизну текста
            if ru_text_normalized != last_spoken_text_normalized or time_since_last_speak > 3.0:
                if ru_text_normalized != last_spoken_text_normalized:
                    print(f"📝 Новый текст (compare): {ru_text[:50]}")
                else:
                    print(f"🔄 Повторение (compare) через {time_since_last_speak:.1f}сек: {ru_text[:50]}")
                
                # Обновляем состояние
                last_spoken_text = ru_text_normalized
                last_spoken_text_time = current_time
                
                # 📤 Отправляем в очередь подготовки аудио
                print(f"📤 Отправили в audio_prep_queue, ocr_session_active={ocr_session_active}")
                audio_prep_queue.put(ru_text)
            else:
                print(f"⏭️ Текст не изменился (compare): {ru_text[:50]}")
        
        except Empty:
            continue
        except Exception as e:
            print(f"⚠️ Ошибка в потоке сравнения: {e}")

def synthesize_tts_task(text_to_synthesize):
    """✅ Одиночная задача TTS синтеза для работы в ThreadPoolExecutor"""
    try:
        import tempfile
        
        print(f"🎙️ TTS синтез начат (pool): '{text_to_synthesize[:40]}'")
        
        # Создаем временный файл для MP3
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, prefix="voice_") as f:
            audio_path = f.name
        
        # === ПРИМЕНЯЕМ СКОРОСТЬ РЕЧИ ===
        multiplier = settings['rate'] / 10.0
        rate_percent = (multiplier - 1) * 100
        rate_str = f"{rate_percent:+.0f}%"
        
        print(f"🎵 Edge TTS скорость (pool): {rate_str}")
        
        # Создаём синтезатор Edge TTS
        communicate = edge_tts.Communicate(text_to_synthesize, voice="ru-RU-DmitryNeural", rate=rate_str)
        
        # Сохраняем в файл (использом asyncio.run для изолированной event loop в пуле)
        asyncio.run(communicate.save(audio_path))
        
        print(f"✅ Аудио готово (pool): {audio_path}")
        
        # 📤 Отправляем готовое аудио в очередь воспроизведения
        ready_audio_queue.put({
            'text': text_to_synthesize,
            'audio_path': audio_path,
            'text_preview': text_to_synthesize[:50]
        })
        
        return audio_path
    
    except Exception as e:
        print(f"❌ Ошибка TTS синтеза (pool): {e}")
        import traceback
        traceback.print_exc()
        return None

def audio_prep_dispatcher_thread():
    """✅ Диспетчер очереди — распределяет задачи TTS в ThreadPoolExecutor пул"""
    global ocr_running, audio_prep_executor
    
    while ocr_running:
        try:
            text_to_synthesize = audio_prep_queue.get(timeout=0.5)
            if not text_to_synthesize:
                continue
            
            # 📤 Отправляем задачу в пул потоков (8-12 параллельных TTS)
            if audio_prep_executor:
                print(f"📤 Диспетчер: отправил в пул TTS: '{text_to_synthesize[:40]}'")
                audio_prep_executor.submit(synthesize_tts_task, text_to_synthesize)
            else:
                print(f"⚠️ Диспетчер: audio_prep_executor=None! Не может отправить")
            
        except Empty:
            continue
        except Exception as e:
            print(f"⚠️ Ошибка диспетчера: {e}")

def ocr_worker_thread_func():
    """Отдельный поток для обработки OCR - не блокирует основной цикл"""
    global ocr_reader, last_ocr_result, previous_text, last_spoken_text_time, last_spoken_text, translation_cache, USE_TESSERACT, ocr_running
    
    while ocr_running:
        try:
            # Берем скриншот из очереди (ждем максимум 0.5сек)
            try:
                screenshot_path = ocr_queue.get(timeout=0.5)
            except Empty:
                # Очередь пуста - продолжаем ждать или завершаемся если флаг ocr_running=False
                continue
            
            # 🔴 КРИТИЧНО: проверяем флаг ДО обработки - если стоп, выходим!
            if not ocr_running:
                break
            
            if not os.path.exists(screenshot_path):
                continue
            
            # Инициализируем OCR если нужно
            if ocr_reader is None:
                init_ocr()
            
            start_ocr = time.time()
            
            # Распознавание текста (Tesseract или EasyOCR)
            try:
                if USE_TESSERACT:
                    img = PILImage.open(screenshot_path)
                    text = pytesseract.image_to_string(img, lang='rus+eng')
                    texts = text.split('\n')
                    texts = [t.strip() for t in texts if t.strip()]
                else:
                    # Fallback на EasyOCR
                    results = ocr_reader.readtext(screenshot_path, detail=0)
                    texts = results if results else []
            except Exception as e:
                # Если Tesseract не работает - отключаем и переходим на EasyOCR
                if USE_TESSERACT and "tesseract is not installed" in str(e).lower():
                    print(f"⚠️ Tesseract не найден, переходим на EasyOCR")
                    USE_TESSERACT = False
                    if ocr_reader is None:
                        print("🚀 Инициализация EasyOCR...")
                        ocr_reader = easyocr.Reader(['en', 'ru'], gpu=False)
                        print("✅ EasyOCR готов")
                    # Пробуем ещё раз с EasyOCR
                    try:
                        results = ocr_reader.readtext(screenshot_path, detail=0)
                        texts = results if results else []
                    except:
                        texts = []
                else:
                    texts = []
            
            ocr_time = time.time() - start_ocr
            print(f"⏱️ OCR обработка: {ocr_time:.3f}сек")
            
            if not texts:
                continue
            
            text = " ".join(texts)
            
            # Быстрый пропуск если текст не изменился
            if text == last_ocr_result:
                continue
            
            last_ocr_result = text
            
            # === ИСПРАВЛЕНИЯ ЛАТИНИЦЫ НА КИРИЛЛИЦУ ===
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
                text = re.sub(f'([а-яА-ЯЁё0-9]){re.escape(latin)}([а-яА-ЯЁё0-9])', 
                             f'\\1{cyrillic}\\2', text)
            
            # === ИСПРАВЛЕНИЯ ОПЕЧАТОК ===
            fixes = {
                r'\bЗННЕТ\b': 'ЗНАЕТ',
                r'\bМЕЕТСЯ\b': 'МЕЖДО',
                '0': 'о',
                r'(\d)\s0': r'\1 о',
            }
            for pattern, repl in fixes.items():
                text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
            
            # Знаем кэш переводов
            if text in translation_cache:
                ru_text = translation_cache[text]
            else:
                translator = GoogleTranslator(source='auto', target='ru')
                ru_text = translator.translate(text)
                translation_cache[text] = ru_text
            
            # ✅ ОТПРАВЛЯЕМ В ОЧЕРЕДЬ СРАВНЕНИЯ (вместо speak_text())
            text_comparison_queue.put(ru_text)
        
        except Exception as e:
            print(f"⚠️ Ошибка OCR потока: {e}")

def process_text():
    """Кладет скриншот в очередь (максимум 1 непроверенный скриншот одновременно)"""
    global previous_screenshot_mtime
    
    if not os.path.exists("screenshot.png"):
        return
    
    # Проверяем изменился ли скриншот по времени
    current_mtime = os.path.getmtime("screenshot.png")
    if current_mtime == previous_screenshot_mtime:
        return
    
    previous_screenshot_mtime = current_mtime
    
    # === ОГРАНИЧЕНИЕ ОЧЕРЕДИ: не более 1 необработанного скриншота ===
    # Если в очереди уже есть скриншот, не интересует фон - текст будет проверен
    if ocr_queue.qsize() < 2:  # Максимум 1 в очереди
        ocr_queue.put("screenshot.png")


def background_loop():
    """Фоновой цикл - быстро захватывает скриншоты и кладет в очередь для асинхронной обработки"""
    global ocr_running
    
    try:
        # Инициализируем OCR
        init_ocr()
        
        # Запускаем отдельный поток для обработки OCR
        ocr_thread = threading.Thread(target=ocr_worker_thread_func, daemon=True)
        ocr_thread.start()
        print("🔄 OCR поток запущен (асинхронная обработка)")
        
        check_interval = 0.1  # Очень быстрые проверки - просто захват без обработки
        
        while ocr_running:  # 🔧 ИСПРАВЛЕННО: проверяем флаг
            try:
                take_screenshot()
                process_text()  # Просто кладет в очередь - не ждет результата
                time.sleep(check_interval)
            except Exception as e:
                print(f"⚠️ Ошибка в цикле захвата: {e}")
                time.sleep(0.1)
    except Exception as e:
        print(f"❌ Критическая ошибка в background_loop: {e}")
    finally:
        print("⏹️ Background loop завершён")

def take_screenshot():
    try:
        start_capture = time.time()
        
        with mss.mss() as sct:
            coords = None
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r") as f:
                    parts = f.read().strip().split(",")
                    if len(parts) == 4:
                        x, y, w, h = map(int, parts)
                        coords = {"top": y, "left": x, "width": w, "height": h}
            
            if coords:
                screenshot = sct.grab(coords)
            else:
                monitor = sct.monitors[1]
                screenshot = sct.grab(monitor)

            img = PilImage.frombytes("RGB", screenshot.size, screenshot.rgb)
            img.save("screenshot.png")
            
        total_capture = time.time() - start_capture
        print(f"📸 Захват: {total_capture:.3f}сек")
        
    except Exception as e:
        print(f"❌ Ошибка захвата: {e}")

if __name__ == "__main__":
    print("🎮 Запуск игрового ассистента...")
    
    # Запускаем главное окно приложения
    show_settings()
