import asyncio
from datetime import datetime, timedelta
from config.config import bot, dp
from database import SessionLocal
from utils import setup_logger
from utils.keyboards import *
from handlers import start_handler, user_handlers, admin_handlers, default_handler

# Настройка логгера
logger = setup_logger()


# Регистрация хэндлеров
dp.include_router(start_handler.start_router)
dp.include_router(admin_handlers.admin_router)
dp.include_router(user_handlers.user_router)
dp.include_router(default_handler.default_router)


# Запуск бота
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    with SessionLocal() as start_session:
        courts = start_session.query(Courts).all()
        if not courts:
            test_court = Courts(name="Тестовый корт", current_password="qwe", previous_password="qwe",
                                password_expiration_date=datetime.now() - timedelta(days=1))
            start_session.add(test_court)
            start_session.commit()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Произошла ошибка: {str(e)}", exc_info=True)
