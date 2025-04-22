import logging
import os
from logging.handlers import RotatingFileHandler

# Создаем папку для логов, если её нет
os.makedirs("logs", exist_ok=True)


def setup_logger():
    # Создаем логгер
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)  # Устанавливаем уровень логгирования
    # logging.getLogger("aiogram").setLevel(logging.WARNING)

    # Форматтер для логов
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Консольный обработчик
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Файловый обработчик (ротация по размеру файла)
    file_handler = RotatingFileHandler(
        "logs/bot.log", maxBytes=5 * 1024 * 1024, backupCount=3
    )  # Максимальный размер файла: 5MB, сохраняем последние 3 файла
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
