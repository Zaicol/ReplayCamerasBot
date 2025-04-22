import os
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
API_TOKEN = os.getenv('CAMERA_API_TOKEN')
DATABASE_URL = os.getenv('CAMERA_DATABASE_URL')
VERSION = os.getenv('CAMERA_VERSION')
