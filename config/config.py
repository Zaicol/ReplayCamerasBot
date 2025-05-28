import os
from collections import deque
from pathlib import Path

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
FRAME_WIDTH = int(os.getenv('CAMERA_FRAME_WIDTH', 0))
FRAME_HEIGHT = int(os.getenv('CAMERA_FRAME_HEIGHT', 0))
MAX_FRAMES = BUFFER_DURATION * FPS
SEGMENT_DIR = Path("segments")
SEGMENT_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR = Path("ffmpeg_pid")
PID_DIR.mkdir(parents=True, exist_ok=True)

buffers: dict[int, deque] = {}
totp_dict: dict[int, TOTP] = {}

# Инициализация бота
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
