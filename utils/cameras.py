import json
from pathlib import Path

import asyncio
import logging

from aiogram import types
from aiogram.types import FSInputFile

from config.config import VERSION, MAX_FRAMES, SEGMENT_DIR
from database.models import Users

logger = logging.getLogger(__name__)

logger.info(f"Максимальное количество кадров в буфере: {MAX_FRAMES}")

# Параметры для запуска ffmpeg
CREATE_NO_WINDOW = 0x08000000
# Максимальное количество неудачных чтений ffmpeg
MAX_BAD_READS = 20
SEGMENT_TIME = 5


async def check_rtsp_connection(camera, timeout: int = 5) -> bool:
    rtsp_url = (
        f"rtsp://{camera.login}:{camera.password}@{camera.ip}:{camera.port}"
        "/cam/realmonitor?channel=1&subtype=0"
    )

    cmd = [
        "ffmpeg", "-rtsp_transport", "tcp", "-i", rtsp_url,
        "-t", "1",              # Читаем 1 секунду потока
        "-f", "null", "-"       # Выводим в никуда (null)
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(process.communicate(), timeout=timeout)
        return process.returncode == 0
    except (asyncio.TimeoutError, Exception):
        return False


async def get_video_resolution(video_path):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(video_path)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()

    info = json.loads(out)
    width = info['streams'][0]['width']
    height = info['streams'][0]['height']
    return width, height


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

    # Получаем разрешение первого сегмента
    try:
        width, height = await get_video_resolution(last_segs[0])
    except Exception as e:
        logger.error(f"Не удалось получить разрешение видео: {str(e)}", exc_info=True)
        await message.answer("Не получилось сохранить видео.")
        return
    watermark_file = "media/" + ("watermark_1080.png" if height >= 1080 else "watermark_720.png")

    # Готовим файл inputs.txt с абсолютными путями
    inputs_txt = Path("inputs.txt")
    with inputs_txt.open("w", encoding="utf-8") as f:
        for seg in last_segs:
            abs_path = seg.resolve().as_posix()
            f.write(f"file '{abs_path}'\n")

    # Итоговый путь для сохранения видео
    output_concat_filename = f"video_camera_{camera_id}_user_{user.id}_concat.mp4"
    output_concat_path = SEGMENT_DIR / output_concat_filename
    output_filename = f"video_camera_{camera_id}_user_{user.id}.mp4"
    output_path = SEGMENT_DIR / output_filename

    # Шаг 1: Склеиваем сегменты
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(inputs_txt),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_concat_path)
    ]

    # Запускаем процесс и ждём завершения
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"FFmpeg concat failed:\n{err.decode(errors='ignore')}")
        await message.answer("Не удалось собрать видео.")
        return

    # Шаг 2: Наложение водяного знака
    cmd_overlay = [
        "ffmpeg", "-y",
        "-i", str(output_concat_path),
        "-i", watermark_file,
        "-filter_complex",
        (
            "[0:v][1:v]overlay=0:0,setsar=1,setdar=16/9"
        ),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-an",
        "-movflags", "+faststart",
        str(output_path)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd_overlay,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"FFmpeg overlay failed:\n{err.decode(errors='ignore')}")
        await message.answer("Не удалось наложить водяной знак.")
        return

    return FSInputFile(str(output_path))
