import asyncio
import logging
from datetime import datetime, timedelta
from config.config import API_TOKEN
from database import SessionLocal
from aiogram import Bot, Dispatcher
from utils import setup_logger
from utils.keyboards import *
from handlers import start_handler, user_handlers, admin_handlers

# Настройка логирования

# Инициализация бота
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Настройка логгера
logger = setup_logger()


# Регистрация хэндлеров
start_handler.register_handlers(dp)
admin_handlers.register_handlers(dp)
user_handlers.register_handlers(dp, bot)


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
