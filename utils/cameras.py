import asyncio
from time import sleep
import cv2
import logging
import threading
from collections import deque

from aiogram import types
from aiogram.types import FSInputFile
from database import SessionLocal, get_all
from database.models import Cameras, Users

logger = logging.getLogger(__name__)

BUFFER_DURATION = 40  # Длительность буфера в секундах
FPS = 20  # Частота кадров (примерное значение)
MAX_FRAMES = BUFFER_DURATION * FPS  # Максимальное количество кадров в буфере
logger.info(f"Максимальное количество кадров в буфере: {MAX_FRAMES}")


# Фоновая задача для записи видео в буфер
def capture_video(camera: Cameras, buffer: deque):
    # RTSP настройки камеры
    rtsp_url = f"rtsp://{camera.login}:{camera.password}@{camera.ip}:{camera.port}/cam/realmonitor?channel=1&subtype=0"

    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        logging.error("Ошибка: Не удалось подключиться к видеопотоку.")
        return

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            logging.error("Ошибка: Не удалось получить кадр из видеопотока. Повторная попытка...")
            sleep(1)
            continue

        # Добавляем кадр в буфер
        buffer.append(frame)


cameras: list[Cameras] = get_all(SessionLocal(), 'cameras')

buffers = {camera.id: deque(maxlen=MAX_FRAMES) for camera in cameras}

for camera in cameras:
    # Запуск захвата видео в отдельном потоке
    capture_thread = threading.Thread(target=capture_video, args=(camera, buffers[camera.id]), daemon=True)
    capture_thread.start()
    logger.info(f"Запущен поток захвата видео для камеры {camera.name}")


async def save_video(user: Users, message: types.Message):
    camera = user.court.cameras[0]
    # Получаем буфер видео
    temp_video_path = f"temp_video_camera_{camera.id}.mp4"

    # Создаем копию буфера для безопасной итерации
    buffer_copy = list(buffers[camera.id])  # Копируем содержимое буфера

    if len(buffer_copy) == 0:
        await message.answer("Буфер пуст. Нечего сохранять.")
        return

    # Получаем параметры видео из первого кадра
    frame_width = buffer_copy[0].shape[1]
    frame_height = buffer_copy[0].shape[0]

    def write_video():
        # Создаем VideoWriter
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_video_path, fourcc, FPS, (frame_width, frame_height))

        # Записываем кадры
        for frame in buffer_copy:
            out.write(frame)

        # Освобождаем ресурсы
        out.release()

    # Выполняем запись видео в отдельном потоке
    await asyncio.to_thread(write_video)

    # Транскодирование видео в H.264
    transcoded_video_path = f"transcoded_temp_video.mp4"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i", temp_video_path,
        "-c:v", "libx264",  # Кодек H.264
        "-preset", "fast",
        transcoded_video_path
    )
    await process.communicate()

    # Отправка видео в Telegram
    video_file = FSInputFile(transcoded_video_path)

    return video_file
