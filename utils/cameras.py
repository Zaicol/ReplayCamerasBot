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
        "-f", "concat", "-safe", "0",
        "-i", str(inputs_txt),
        "-c", "copy",
        "-movflags", "+faststart",
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
