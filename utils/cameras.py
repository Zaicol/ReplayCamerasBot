import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
import asyncio
from time import sleep

import aiohttp
import pandas as pd
import requests
from aiogram.types import FSInputFile, Message
from config.config import SEGMENT_DIR, PID_DIR, SEGMENT_TIME, SEGMENT_WRAP, BUFFER_DURATION, SEND_CHANNEL, \
    last_clusters, CUT_DURATION
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


async def save_video(user_id: int, camera_id: int, message: Message | None, offset: int = 0):
    # Определяем количество сегментов, которое нужно собрать
    count = (CUT_DURATION + SEGMENT_TIME - 1) // SEGMENT_TIME + 1
    if offset + CUT_DURATION > BUFFER_DURATION:
        logger.error(f"Слишком большой офсет! ({offset} + {CUT_DURATION} > {BUFFER_DURATION})")
        offset = 0

    # Выбираем сегменты для конкретной камеры
    seg_pattern = f"buffer_{camera_id}_*.mp4"
    # Собираем все сегменты и сортируем их по времени модификации (хронологически)
    segs = list(SEGMENT_DIR.glob(seg_pattern))
    segs.sort(key=lambda p: p.stat().st_mtime)

    if not segs and message is not None:
        await message.answer("Буфер пуст. Нечего сохранять.")
        return

    # Берём последние count сегментов в хронологическом порядке
    offset_files = offset // SEGMENT_TIME
    last_segs = segs[-count-offset_files:-offset_files]

    # Получаем разрешение первого сегмента
    try:
        width, height = await get_video_resolution(last_segs[0])
    except Exception as e:
        logger.error(f"Не удалось получить разрешение видео: {str(e)}", exc_info=True)
        if message is not None:
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
    output_concat_path = SEGMENT_DIR / f"video_camera_{camera_id}_user_{user_id}_concat.mp4"
    output_watermark_path = SEGMENT_DIR / f"video_camera_{camera_id}_user_{user_id}.mp4"

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
        if message is not None:
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
        if message is not None:
            await message.answer("Не удалось наложить водяной знак.")
        return

    return FSInputFile(str(output_watermark_path))


async def async_get(url, auth):
    def sync_request():
        try:
            response = requests.get(url, auth=auth, timeout=10)
            logger.info(f"GET-запрос: {url} - {response.status_code}")
            return response.status_code, response.text.strip()
        except Exception as e:
            logger.error(f"Ошибка при GET-запросе: {url}\n{e}")
            return None, ""

    return await asyncio.to_thread(sync_request)


# --- Получение следующей порции видео ---
async def get_next_videos(session, ip, auth, object_id):
    url = f"http://{ip}/cgi-bin/mediaFileFind.cgi?action=findNextFile&object={object_id}&count=100"
    status, response_text = await async_get(url, auth)

    if status != 200:
        logger.error(f"Ошибка при findNextFile: {response_text}")
        return pd.DataFrame()

    lines = [line.strip() for line in response_text.splitlines() if line.startswith('items')]
    data = {}

    for line in lines:
        match = re.match(r'items\[(\d+)\]\.([^\=]+)=(.+)', line)
        if match:
            index, key, value = match.groups()
            index = int(index)
            if index not in data:
                data[index] = {}
            data[index][key] = value

    return pd.DataFrame.from_dict(data, orient='index')


async def destroy_find_object(ip, auth, object_id):
    url = f"http://{ip}/cgi-bin/mediaFileFind.cgi?action=factory.destroy&object={object_id}"
    requests.get(url, auth=auth)


# --- Получение последнего события AlarmLocal ---
async def get_latest_alarm_local_video(ip, auth, channel):
    end_time = datetime.now() + timedelta(minutes=5)
    start_time = end_time - timedelta(minutes=15)
    start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
    end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    storage_path = "/dev/sda"

    async with aiohttp.ClientSession() as session:
        # 1. Создание объекта поиска
        create_url = f"http://{ip}/cgi-bin/mediaFileFind.cgi?action=factory.create"
        status, text = await async_get(create_url, auth)
        if status != 200:
            logger.error("Ошибка создания объекта поиска: %s", text)
            return None

        object_id = text.split("=")[-1].strip()
        logger.info(f"Channel: {channel}, Object ID: {object_id}")

        # 2. Инициация поиска
        start_find_url = (
            f"http://{ip}/cgi-bin/mediaFileFind.cgi?action=findFile"
            f"&object={object_id}"
            f"&condition.Channel={channel}"
            f"&condition.StartTime={start_time_str}"
            f"&condition.EndTime={end_time_str}"
            f"&condition.Dirs=n&condition.Dirs[0]={storage_path}"
        )

        status, text = await async_get(start_find_url, auth)
        if status != 200 or "false" in text:
            logger.error("Ошибка начала поиска: %s", text)
            return None

        # 3. Получение видео с событиями
        while True:
            df = await get_next_videos(session, ip, auth, object_id)
            if df.empty:
                break

            df['is_alarm'] = df.filter(like='Events').apply(
                lambda row: 'AlarmLocal' in row.values.astype(str),
                axis=1
            )
            alarm_df = df[df['is_alarm']]

            if alarm_df.empty:
                continue

            latest_row = alarm_df.sort_values(by='Cluster', ascending=False).iloc[0]
            cluster = latest_row.get('Cluster', None)
            if cluster:
                await destroy_find_object(ip, auth, object_id)
                return cluster

        await destroy_find_object(ip, auth, object_id)
        return None


# --- Цикл проверки тревог ---
async def check_alarm(ip, auth, channel, bot):
    logger.info(f" Проверка канала {channel} ".center(80, '='))
    last_cluster = last_clusters.get(channel, None)
    cluster = await get_latest_alarm_local_video(ip, auth, channel)
    try:
        cluster = int(cluster) if cluster is not None else None
    except (ValueError, TypeError):
        logger.error(f"Канал {channel} - Ошибка парсинга кластера: {cluster}")
        cluster = None

    if cluster is not None and (last_cluster is None or cluster > last_cluster):
        last_cluster = cluster
        await bot.send_message(chat_id=289208255, text=f"Обнаружено событие в камере: {cluster} (канал {channel})")
        await save_and_send_video_to_channel(channel, bot)

    last_clusters[channel] = last_cluster
    logger.info(f" Канал {channel} - Последний кластер: {last_cluster} ".center(80, '='))


async def check_alarm_cycle(ip, auth, bot, channel_end):
    while True:
        for i in range(1, channel_end + 1):
            await check_alarm(ip, auth, i, bot)
        await asyncio.sleep(10)


async def save_and_send_video_to_channel(camera_id, bot) -> bool:
    video_file = await save_video(camera_id, camera_id, None, 60)

    if video_file is None:
        bot.send_message(chat_id=289208255, text=f"Ошибка при сохранении видео по кнопке. Камера: {camera_id}")
        return False
    chan = SEND_CHANNEL
    sent_message = await bot.send_video(chat_id=chan, video=video_file)

    # TODO: Добавить сохранение в БД
    # async with AsyncSessionLocal() as session:
    #     await create_item(
    #         session, 'videos',
    #         video_id=sent_message.video.file_id,
    #         timestamp=datetime.now(),
    #         user_id=message.from_user.id,
    #         court_id=user.selected_court_id
    #     )
    #     await session.commit()

    try:
        os.remove(video_file.path)
        os.remove(video_file.path.replace('.mp4', '_concat.mp4'))
    except Exception as e:
        logging.error(f"Ошибка при удалении файла: {e}")

    return True
