import asyncio
import os

from pyotp import TOTP
from database import AsyncSessionLocal, init_models, engine, Cameras, get_all, Courts, set_secret_for_all_courts
from handlers import start_router, admin_router, user_router, default_router
from config.config import bot, dp, totp_dict, recorder_ip, recorder_auth
from utils import setup_logger
from utils.cameras import start_buffer, check_alarm

# Настройка логгера
logger = setup_logger()

# Регистрация хэндлеров
dp.include_router(start_router)
dp.include_router(admin_router)
dp.include_router(user_router)
dp.include_router(default_router)


async def on_startup() -> None:
    """Функция, вызываемая при запуске бота. Запускает буферы для камер."""
    async with AsyncSessionLocal() as session:
        cameras: list[Cameras] = await get_all(session, 'cameras')

    for camera in cameras:
        asyncio.create_task(start_buffer(camera))
        logger.info(f"Запущен поток захвата видео для камеры {camera.name}")


async def main():
    """Основная асинхронная точка входа."""
    await init_models(engine)

    async with AsyncSessionLocal() as session:
        courts: list[Courts] = await get_all(session, 'courts')
        await set_secret_for_all_courts(session)

    # Создание TOTP объектов для всех кортов
    for court in courts:
        totp_dict[court.id] = TOTP(court.totp_secret, interval=3600, digits=4)

    for i in range(1, 4):
        asyncio.create_task(check_alarm(recorder_ip, recorder_auth, i, bot))

    # Запуск бота
    await dp.start_polling(bot)


if __name__ == "__main__":
    # Сохранение PID в файл для отслеживания процесса
    with open("bot.pid", "w") as f:
        f.write(str(os.getpid()))

    try:
        # Регистрация функции старта
        dp.startup.register(on_startup)
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Произошла ошибка: {str(e)}", exc_info=True)
