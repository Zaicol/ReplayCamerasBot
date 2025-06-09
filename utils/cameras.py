import json
import logging
from pathlib import Path
import asyncio


from aiogram.types import FSInputFile, Message
from config.config import STAND_VERSION, SEGMENT_DIR, PID_DIR, SEGMENT_TIME, SEGMENT_WRAP, BUFFER_DURATION
from database.models import Users
from utils import setup_logger

logger = logging.getLogger(__name__)
logger_ffmpeg = setup_logger("ffmpeg")


async def check_rtsp_connection(camera, timeout: int = 5) -> bool:
    rtsp_url = (
        f"rtsp://{camera.login}:{camera.password}@{camera.ip}:{camera.port}"
        "/cam/realmonitor?channel=1&subtype=0"
    )

    cmd = [
        "ffmpeg", "-rtsp_transport", "tcp", "-i", rtsp_url,
        "-t", "1",
        "-f", "null", "-"
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


async def start_buffer(camera):
    """
    Запускает поток захвата видео для камеры.
    Видео записывается как rolling buffer - набор циклически пишущихся сегментов.
    """

    async def log_stream(stream, log_func, camera_name):
        while True:
            line = await stream.readline()
            if not line:
                break
            log_func(f"[{camera_name}] {line.decode(errors='ignore').strip()}")

    rtsp_url = (
        f"rtsp://{camera.login}:{camera.password}@{camera.ip}:{camera.port}"
        "/cam/realmonitor?channel=1&subtype=0"
    )

    cmd = [
        "ffmpeg", "-rtsp_transport", "tcp", "-i", rtsp_url,
        "-c", "copy", "-f", "segment",
        "-aspect", "16:9",
        "-segment_time", str(SEGMENT_TIME),
        "-segment_wrap", str(SEGMENT_WRAP),
        "-reset_timestamps", "1",
        "-loglevel", "info",
        str(SEGMENT_DIR / f"buffer_{camera.id}_%03d.mp4")
    ]

    while True:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        with open(PID_DIR / f"ffmpeg_{camera.id}.pid", "w+") as pid_f:
            pid_f.write(str(process.pid))

        logger.info(f"Запущен поток захвата видео для камеры {camera.name} по адресу {rtsp_url}")

        await asyncio.gather(
            log_stream(process.stderr, logger_ffmpeg.warning, camera.name),
            process.wait()
        )

        logger.warning(f"FFmpeg завершил работу для камеры {camera.name}. Перезапуск через 5 секунд.")
        await asyncio.sleep(5)


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
    out, _ = await proc.communicate()

    info = json.loads(out)
    width = info['streams'][0]['width']
    height = info['streams'][0]['height']
    return width, height


async def save_video(user: Users, message: Message):
    # Определяем количество сегментов, которое нужно собрать
    count = (BUFFER_DURATION + SEGMENT_TIME - 1) // SEGMENT_TIME + 1
    print(count, BUFFER_DURATION, SEGMENT_TIME)

    # Выбираем сегменты для конкретной камеры
    camera_id = user.court.cameras[0].id if STAND_VERSION != "test" else -1
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
    output_concat_path = SEGMENT_DIR / f"video_camera_{camera_id}_user_{user.id}_concat.mp4"
    output_watermark_path = SEGMENT_DIR / f"video_camera_{camera_id}_user_{user.id}.mp4"

    # Шаг 1: Склейка сегментов
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(inputs_txt),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_concat_path)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, err = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"Не удалось собрать видео:\n{err.decode(errors='ignore')}")
        await message.answer("Не удалось собрать видео.")
        return

    # Шаг 2: Наложение водяного знака
    cmd_overlay = [
        "ffmpeg", "-y",
        "-i", str(output_concat_path),
        "-i", watermark_file,
        "-filter_complex", "[0:v][1:v]overlay=0:0,setsar=1,setdar=16/9",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-an",
        "-movflags", "+faststart",
        str(output_watermark_path)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd_overlay,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, err = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"Не удалось наложить водяной знак:\n{err.decode(errors='ignore')}")
        await message.answer("Не удалось наложить водяной знак.")
        return

    return FSInputFile(str(output_watermark_path))
