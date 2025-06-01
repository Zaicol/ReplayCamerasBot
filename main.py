import asyncio
import os

from pyotp import TOTP
from database import AsyncSessionLocal, init_models, engine, Cameras, get_all, Courts, set_secret_for_all_courts
from config.config import bot, dp, totp_dict, SEGMENT_DIR, PID_DIR
from utils import setup_logger
from handlers import *

# Настройка логгера
logger = setup_logger()

# Регистрация хэндлеров
dp.include_router(start_router)
dp.include_router(admin_router)
dp.include_router(user_router)
dp.include_router(default_router)


async def log_stream(stream, log_func, camera_name):
    while True:
        line = await stream.readline()
        if not line:
            break
        log_func(f"[{camera_name}] {line.decode(errors='ignore').strip()}")


async def start_buffer(camera):
    rtsp_url = (
        f"rtsp://{camera.login}:{camera.password}@{camera.ip}:{camera.port}"
        "/cam/realmonitor?channel=1&subtype=0"
    )
    watermark_path = os.path.join("media", "watermark_full.png")
    # Запустим ffmpeg в фоновом процессе
    cmd = [
        "ffmpeg", "-rtsp_transport", "tcp", "-i", rtsp_url,
        "-c", "copy", "-f", "segment",
        # Указываем правильное соотношение сторон
        "-aspect", "16:9",

        "-fflags", "+genpts",
        "-segment_time", "5",
        "-segment_wrap", "15",
        "-reset_timestamps", "1",
        "-loglevel", "info",
        str(SEGMENT_DIR / f"buffer_{camera.id}_%03d.mp4")
    ]
    # cmd = [
    #     "ffmpeg", "-rtsp_transport", "tcp", "-i", rtsp_url,
    #     "-i", str(watermark_path),
    #
    #     # Добавляем format=yuv420p для совместимости с iPhone
    #     "-filter_complex",
    #     "[0:v][1:v]overlay=0:0,format=yuv420p,scale=1920:1080",
    #
    #     # Гарантируем ключевые кадры каждые 5 сек
    #     "-force_key_frames", "expr:gte(t,n_forced*5)",
    #     "-g", "125",
    #
    #     # Перекодируем видео
    #     "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
    #
    #     # Аудио копируем
    #     "-c:a", "copy",
    #
    #     # Сегментация
    #     "-f", "segment",
    #     "-fflags", "+genpts",
    #     "-segment_time", "5",
    #     "-segment_wrap", "15",
    #     "-reset_timestamps", "1",
    #
    #     # Без лишнего вывода
    #     "-loglevel", "warning",
    #
    #     # Выходной файл
    #     str(SEGMENT_DIR / f"buffer_{camera.id}_%03d.mp4")
    # ]

    while True:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        with open(PID_DIR / f"ffmpeg_{camera.id}.pid", "w+") as pid_f:
            pid_f.write(str(process.pid))

        logger.info(f"Запущен поток захвата видео для камеры {camera.name} по адресу {rtsp_url}")

        # Параллельно логируем stdout и stderr
        await asyncio.gather(
            # log_stream(process.stdout, logger.info, camera.name),
            # log_stream(process.stderr, logger.warning, camera.name),
            process.wait()
        )

        logger.warning(f"FFmpeg завершил работу для камеры {camera.name}. Перезапуск через 5 секунд.")
        await asyncio.sleep(5)


async def on_startup() -> None:
    async with AsyncSessionLocal() as session:
        cameras: list[Cameras] = await get_all(session, 'cameras')

    # Создание и запуск буфферов
    for camera in cameras:
        # Запуск захвата видео в отдельном потоке
        asyncio.create_task(start_buffer(camera))
        logger.info(f"Запущен поток захвата видео для камеры {camera.name}")


# Запуск бота
async def main():
    await init_models(engine)

    async with AsyncSessionLocal() as session:
        courts: list[Courts] = await get_all(session, 'courts')
        await set_secret_for_all_courts(session)

    # Создание totp объектов
    for court in courts:
        totp_dict[court.id] = TOTP(court.totp_secret, interval=3600, digits=4)

    # Запуск бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    with open("bot.pid", "w") as f:
        f.write(str(os.getpid()))

    try:
        dp.startup.register(on_startup)
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Произошла ошибка: {str(e)}", exc_info=True)
