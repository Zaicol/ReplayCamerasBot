import cv2
import asyncio
import logging
from collections import deque

from aiogram import types
from aiogram.types import FSInputFile

from config.config import VERSION, FPS, buffers, MAX_FRAMES
from database.models import Cameras, Users
import subprocess as sp
import numpy as np
import time as t

logger = logging.getLogger(__name__)

logger.info(f"Максимальное количество кадров в буфере: {MAX_FRAMES}")

# Параметры для запуска ffmpeg
CREATE_NO_WINDOW = 0x08000000

# Фоновая задача для записи видео в буфер
def capture_video(camera: Cameras, buffer: deque):
    rtsp_url = f"rtsp://{camera.login}:{camera.password}@{camera.ip}:{camera.port}/cam/realmonitor?channel=1&subtype=0"
    time_to_sleep = 1 / FPS
    logger.info(f"Запущен поток захвата видео для камеры {camera.name} по адресу {rtsp_url}")

    width, height = 1216, 684
    frame_size = width * height * 3

    command = [
        'ffmpeg',
        '-loglevel', 'quiet',
        '-rtsp_transport', 'tcp',
        '-i', rtsp_url,
        '-pix_fmt', 'bgr24',
        '-s', f'{width}x{height}',
        '-f', 'image2pipe',
        '-vcodec', 'rawvideo', '-']

    process = sp.Popen(command, stdout=sp.PIPE, stderr=sp.DEVNULL, creationflags=CREATE_NO_WINDOW)

    while True:
        raw_frame = process.stdout.read(frame_size)
        if not raw_frame or len(raw_frame) < frame_size:
            logging.error("Ошибка: Не удалось получить корректный кадр. Перезапуск...")
            process.kill()
            process = sp.Popen(command, stdout=sp.PIPE, stderr=sp.DEVNULL, creationflags=CREATE_NO_WINDOW)
            continue

        frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((height, width, 3))
        buffer.append(frame.copy())

        # Ограничиваем размер буфера
        if len(buffer) > buffer.maxlen:
            buffer.popleft()

        t.sleep(time_to_sleep)  # Легкая пауза, чтобы не перегружать CPU


def load_video_to_buffer():
    cap = cv2.VideoCapture("temp_video_camera_1.mp4")
    if not cap.isOpened():
        raise IOError(f"Не удалось открыть видеофайл: temp_video_camera_1.mp4")

    buffer = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        resized = cv2.resize(frame, (1216, 684))
        buffer.append(resized)

    cap.release()
    return buffer


async def save_video(user: Users, message: types.Message):
    if VERSION == "test":
        buffer_copy = load_video_to_buffer()
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

    output_path = f"video_camera_{camera_id}_user_{user.id}.mp4"

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
        "-f", "mp4",
        output_path
    ]

    # Запускаем FFmpeg как подпроцесс
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=CREATE_NO_WINDOW
    )

    async def read_stream(stream):
        while not stream.at_eof():
            line = await stream.readline()
            if line:
                print(line.decode(errors="ignore").strip())

    log_task = asyncio.create_task(read_stream(process.stderr))

    try:
        for frame in buffer_copy:
            process.stdin.write(frame.tobytes())
            await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError) as e:
        await message.answer("Ошибка при записи видео. FFmpeg закрыл соединение.")
        print(f"Write error: {e}")
        return

    process.stdin.close()
    try:
        await process.stdin.wait_closed()
    except Exception as e:
        print(f"stdin.wait_closed() failed: {e}")

    return_code = await process.wait()
    await log_task

    if return_code != 0:
        error_output = await process.stderr.read()
        print("FFmpeg error output:\n", error_output.decode(errors="ignore"))
        await message.answer("Произошла ошибка при сохранении видео.")
        return

    # Отправляем видео
    video_file = FSInputFile(output_path)
    return video_file
