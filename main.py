import asyncio
import threading
from collections import deque
from config.config import bot, dp, MAX_FRAMES, buffers, totp_dict
from database import AsyncSessionLocal, init_models, engine, Cameras, get_all, Courts
from utils import setup_logger
from handlers import start_handler, user_handlers, admin_handlers, default_handler
from utils.cameras import capture_video
from pyotp import TOTP

# Настройка логгера
logger = setup_logger()


# Регистрация хэндлеров
dp.include_router(start_handler.start_router)
dp.include_router(admin_handlers.admin_router)
dp.include_router(user_handlers.user_router)
dp.include_router(default_handler.default_router)


# Запуск бота
async def main():
    await init_models(engine)

    # Создание и запуск буфферов
    async with AsyncSessionLocal() as session:
        cameras: list[Cameras] = await get_all(session, 'cameras')
        courts: list[Courts] = await get_all(session, 'courts')

    buffers.update({camera.id: deque(maxlen=MAX_FRAMES) for camera in cameras})

    for camera in cameras:
        # Запуск захвата видео в отдельном потоке
        capture_thread = threading.Thread(target=capture_video, args=(camera, buffers[camera.id]), daemon=True)
        capture_thread.start()
        logger.info(f"Запущен поток захвата видео для камеры {camera.name}")

    # Создание totp
    for court in courts:
        totp_dict[court.id] = TOTP(court.totp_secret, interval=3600, digits=4)

    # Запуск бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Произошла ошибка: {str(e)}", exc_info=True)
