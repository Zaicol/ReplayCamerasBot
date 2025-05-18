import os

from aiogram import Dispatcher, Bot
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
API_TOKEN = os.getenv('CAMERA_API_TOKEN')
DATABASE_URL = os.getenv('CAMERA_DATABASE_URL')
VERSION = os.getenv('CAMERA_VERSION')
BUFFER_DURATION = int(os.getenv('CAMERA_BUFFER_DURATION', 40))
FPS = int(os.getenv('CAMERA_FPS', 25))
MAX_FRAMES = BUFFER_DURATION * FPS

buffers = {}
totp_dict = {}

# Инициализация бота
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
