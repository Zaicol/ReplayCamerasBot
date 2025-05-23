import asyncio
import os
import threading
from pyotp import TOTP
from collections import deque

from database import AsyncSessionLocal, init_models, engine, Cameras, get_all, Courts, set_secret_for_all_courts
from config.config import bot, dp, MAX_FRAMES, buffers, totp_dict
from utils.cameras import capture_video
from utils import setup_logger
from handlers import *

# Настройка логгера
logger = setup_logger()


# Регистрация хэндлеров
dp.include_router(start_router)
dp.include_router(admin_router)
dp.include_router(user_router)
dp.include_router(default_router)


# Запуск бота
async def main():
    await init_models(engine)

    async with AsyncSessionLocal() as session:
        cameras: list[Cameras] = await get_all(session, 'cameras')
        courts: list[Courts] = await get_all(session, 'courts')
        await set_secret_for_all_courts(session)

    # Создание и запуск буфферов
    buffers.update({camera.id: deque(maxlen=MAX_FRAMES) for camera in cameras})
    for camera in cameras:
        # Запуск захвата видео в отдельном потоке
        capture_thread = threading.Thread(target=capture_video, args=(camera, buffers[camera.id]), daemon=True)
        capture_thread.start()
        logger.info(f"Запущен поток захвата видео для камеры {camera.name}")

    # Создание totp объектов
    for court in courts:
        totp_dict[court.id] = TOTP(court.totp_secret, interval=3600, digits=4)

    # Запуск бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    with open("bot.pid", "w") as f:
        f.write(str(os.getpid()))

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Произошла ошибка: {str(e)}", exc_info=True)
