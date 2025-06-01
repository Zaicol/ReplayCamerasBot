import os
import logging
from logging.handlers import RotatingFileHandler

# Создаем папку для логов, если её нет
os.makedirs("logs", exist_ok=True)


def setup_logger(logger_name):
    # Создаем логгер
    if logger_name:
        logger = logging.getLogger(logger_name)
    else:
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
    filename = f"logs/{logger_name}.log" if logger_name else "logs/bot.log"
    file_handler = RotatingFileHandler(
        filename, maxBytes=2 * 1024 * 1024, backupCount=20
    )  # Максимальный размер файла: 2MB, сохраняем последние 20 файлов
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
