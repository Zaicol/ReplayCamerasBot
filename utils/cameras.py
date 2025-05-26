from pathlib import Path

import cv2
import asyncio
import logging
from collections import deque

from aiogram import types
from aiogram.types import FSInputFile

from config.config import VERSION, FPS, buffers, MAX_FRAMES, FRAME_WIDTH, FRAME_HEIGHT, SEGMENT_DIR
from database.models import Cameras, Users
import subprocess as sp
import numpy as np
import time as t

logger = logging.getLogger(__name__)

logger.info(f"Максимальное количество кадров в буфере: {MAX_FRAMES}")

# Параметры для запуска ffmpeg
CREATE_NO_WINDOW = 0x08000000
# Максимальное количество неудачных чтений ffmpeg
MAX_BAD_READS = 20
SEGMENT_TIME = 5  # секунда на один сегмент
BUFFER_SECONDS = 60  # общий размер буфера (5*12 = 60 сек)


# Фоновая задача для записи видео в буфер
def capture_video(camera: Cameras, buffer: deque):
    rtsp_url = (
        f"rtsp://{camera.login}:{camera.password}@{camera.ip}:{camera.port}"
        "/cam/realmonitor?channel=1&subtype=0"
    ) if VERSION != "test2" else (
        f"rtsp://172.28.243.141:8554/mystream"
    )

    width = FRAME_WIDTH if FRAME_WIDTH else 1280
    height = FRAME_HEIGHT if FRAME_HEIGHT else 720
    frame_size = width * height * 3
    time_to_sleep = 1 / FPS
    logger.info(f"Запущен поток захвата видео для камеры {camera.name} по адресу {rtsp_url}")
    logger.info(f"Ширина кадра: {width}, высота кадра: {height}, размер кадра: {frame_size}")

    command = [
        'ffmpeg',
        '-loglevel', 'quiet',
        '-rtsp_transport', 'tcp',
        '-i', rtsp_url,
        '-pix_fmt', 'bgr24',
        '-f', 'image2pipe',
        '-vcodec', 'rawvideo', '-'
    ]

    if FRAME_WIDTH and FRAME_HEIGHT:
        command.insert(-3, '-s')
        command.insert(-3, f'{width}x{height}')

    def start_ffmpeg():
        return sp.Popen(
            command,
            stdout=sp.PIPE,
            stderr=sp.DEVNULL,
            creationflags=CREATE_NO_WINDOW
        )

    process = start_ffmpeg()
    bad_reads = 0

    while True:
        frame = process.stdout.read(frame_size)

        if not frame or len(frame) < frame_size:
            bad_reads += 1
            logger.warning(f"Недостаточно данных от ffmpeg (попытка {bad_reads}/{MAX_BAD_READS})")
            if bad_reads >= MAX_BAD_READS:
                logger.error("Слишком много неудачных чтений. Перезапуск ffmpeg.")
                process.kill()
                process = start_ffmpeg()
                bad_reads = 0
            t.sleep(time_to_sleep)
            continue

        bad_reads = 0

        try:
            frame = np.frombuffer(frame, dtype=np.uint8).reshape((height, width, 3))
        except ValueError:
            logger.warning("Не удалось декодировать кадр. Пропуск.")
            t.sleep(time_to_sleep)
            continue

        buffer.append(frame.copy())
        t.sleep(time_to_sleep)


# Функция только для локальных тестов
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


def get_last_segments(count: int, camera_id: int) -> [Path]:
    files = sorted(SEGMENT_DIR.glob(f"buffer_{camera_id}_*.mp4"))
    return files[-count:]


def make_concat_file(segments: [Path], concat_path: Path):
    with open(concat_path, "w") as f:
        for seg in segments:
            f.write(f"file '{seg.as_posix()}'\n")


def assemble_last(seconds: int, output_path: Path, camera_id: int):
    # сколько сегментов нужно
    seg_len = 5
    count = (seconds + seg_len - 1) // seg_len  # округление вверх
    segs = get_last_segments(count, camera_id)
    concat_txt = SEGMENT_DIR / "inputs.txt"
    make_concat_file(segs, concat_txt)
    sp.run([
        "ffmpeg", "-loglevel", "quiet",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_txt),
        "-c", "copy",
        str(output_path)
    ], check=True)


async def cmd_last(message: types.Message):
    sec = 15  # или парсим аргумент команды
    out = SEGMENT_DIR / f"last_{sec}s.mp4"
    assemble_last(sec, out)
    await message.reply_video(out.open("rb"))


async def save_video(user: Users, message: types.Message, seconds: int = 60):
    # Определяем количество сегментов, которое нужно собрать
    count = (seconds + SEGMENT_TIME - 1) // SEGMENT_TIME

    # Выбираем сегменты для конкретной камеры
    camera_id = user.court.cameras[0].id if VERSION != "test" else -1
    seg_pattern = f"buffer_{camera_id}_*.mp4"
    # Собираем все сегменты и сортируем их по времени модификации (хронологически)
    segs = list(SEGMENT_DIR.glob(seg_pattern))
    segs.sort(key=lambda p: p.stat().st_mtime)

    if not segs:
        await message.answer("Буфер пуст. Нечего сохранять.")
        return

    # Берём последние count сегментов в хронологическом порядке
    last_segs = segs[-count:]
    if len(last_segs) < count:
        await message.answer(f"В буфере всего {len(last_segs) * SEGMENT_TIME} секунд, запишем их все.")

    # Готовим файл inputs.txt с абсолютными путями
    inputs_txt = Path("inputs.txt")
    with inputs_txt.open("w", encoding="utf-8") as f:
        for seg in last_segs:
            abs_path = seg.resolve().as_posix()
            f.write(f"file '{abs_path}'\n")

    # Итоговый путь для сохранения видео
    output_filename = f"video_camera_{camera_id}_user_{user.id}.mp4"
    output_path = SEGMENT_DIR / output_filename

    # Команда для склейки сегментов
    cmd = [
        "ffmpeg", "-y",
        # "-report",                # можно включить для отладки
        "-f", "concat", "-safe", "0",
        "-i", str(inputs_txt),
        "-c", "copy",
        str(output_path)
    ]

    # Запускаем процесс и ждём завершения
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()

    # Если нужно отладить, раскомментируйте:
    # print("FFmpeg stdout:\n", out.decode(errors="ignore"))
    # print("FFmpeg stderr:\n", err.decode(errors="ignore"))

    if proc.returncode != 0:
        logger.error(f"FFmpeg concat failed:\n{err.decode(errors='ignore')}")
        await message.answer("Не удалось собрать видео.")
        return

    # Возвращаем готовое видео
    return FSInputFile(str(output_path))
