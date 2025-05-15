import asyncio
import subprocess
import sys
from time import sleep
import cv2
import logging
import threading
from collections import deque

import numpy as np
from aiogram import types
from aiogram.types import FSInputFile

from config.config import VERSION
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
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
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
    if VERSION == "test":
        frame_height, frame_width = 108, 192
        buffer_copy = [np.random.randint(0, 256, (frame_height, frame_width, 3), dtype=np.uint8) for _ in range(MAX_FRAMES)]
        camera_id = -1
    else:
        camera_id = user.court.cameras[0].id
        buffer_copy = list(buffers[camera_id])  # Копируем буфер

    if len(buffer_copy) == 0:
        await message.answer("Буфер пуст. Нечего сохранять.")
        return

    # Параметры видео
    frame = buffer_copy[0]
    height, width, _ = frame.shape
    fps = FPS  # Убедитесь, что FPS определён

    output_path = f"transcoded_temp_video_camera_{camera_id}.mp4"

    # Команда FFmpeg для записи raw кадров в h264
    command = [
        "ffmpeg",
        "-y",  # Перезаписывать файл
        "-f", "rawvideo",  # Входной формат — raw video
        "-pix_fmt", "bgr24",  # Формат пикселей (OpenCV использует BGR)
        "-s", f"{width}x{height}",  # Размер кадра
        "-r", str(fps),  # FPS
        "-i", "-",  # Ввод из stdin
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",  # Совместимость с проигрывателями
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",  # Избегаем ошибок нечетных размеров
        "-f", "mp4",
        output_path
    ]

    # Запускаем FFmpeg как подпроцесс
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE
    )

    async def read_stream(stream):
        while not stream.at_eof():
            line = await stream.readline()
            if line:
                sys.stdout.write(line.decode(errors='ignore'))
                sys.stdout.flush()

    # Читаем вывод ffmpeg в реальном времени
    log_task = asyncio.create_task(read_stream(process.stderr))

    # Отправляем кадры в stdin FFmpeg
    for frame in buffer_copy:
        process.stdin.write(frame.tobytes())

    # Завершаем запись
    process.stdin.close()
    await process.stdin.wait_closed()
    await process.wait()
    await log_task

    # Отправляем видео
    video_file = FSInputFile(output_path)
    return video_file
