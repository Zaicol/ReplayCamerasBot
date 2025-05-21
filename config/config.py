import os
from collections import deque

from aiogram import Dispatcher, Bot
from dotenv import load_dotenv
from pyotp import TOTP

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
API_TOKEN = os.getenv('CAMERA_API_TOKEN')
DATABASE_URL = os.getenv('CAMERA_DATABASE_URL')
VERSION = os.getenv('CAMERA_VERSION')
BUFFER_DURATION = int(os.getenv('CAMERA_BUFFER_DURATION', 40))
FPS = int(os.getenv('CAMERA_FPS', 25))
FRAME_WIDTH = int(os.getenv('CAMERA_FRAME_WIDTH', None))
FRAME_HEIGHT = int(os.getenv('CAMERA_FRAME_HEIGHT', None))
MAX_FRAMES = BUFFER_DURATION * FPS

buffers: dict[int, deque] = {}
totp_dict: dict[int, TOTP] = {}

# Инициализация бота
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
