import os
from collections import deque
from datetime import datetime
from pathlib import Path

from aiogram import Dispatcher, Bot
from dotenv import load_dotenv
from pyotp import TOTP
from requests.auth import HTTPDigestAuth

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
API_TOKEN = os.getenv('CAMERA_API_TOKEN')
DATABASE_URL = os.getenv('CAMERA_DATABASE_URL')
STAND_VERSION = os.getenv('STAND_VERSION')  # тест или деплой

SEND_CHANNELS = list(map(int, os.getenv('SEND_CHANNELS', '-1002654429486').split(",")))

PID_DIR = Path("ffmpeg_pid")
PID_DIR.mkdir(parents=True, exist_ok=True)

BUFFER_DURATION = int(os.getenv('CAMERA_BUFFER_DURATION', 60))
CUT_DURATION = int(os.getenv('CAMERA_CUT_DURATION', BUFFER_DURATION))
FPS = int(os.getenv('CAMERA_FPS', 25))
SEGMENT_DIR = Path("segments")
SEGMENT_DIR.mkdir(parents=True, exist_ok=True)
SEGMENT_TIME = 5
SEGMENT_WRAP = int(round(BUFFER_DURATION / SEGMENT_TIME * 1.5))  # default = 18

LAST_RESTART = datetime.now()

buffers: dict[int, deque] = {}
totp_dict: dict[int, TOTP] = {}

# Инициализация бота
if API_TOKEN is None:
    raise ValueError("API_TOKEN is not set")
if DATABASE_URL is None:
    raise ValueError("DATABASE_URL is not set")
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Этот параметр ставился во времена, когда функция захвата потока использовала opencv.
# В теории, эту строчку уже можно убрать, но на всякий случай я её оставил.
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"


# Настройки регистратора
recorder_ip = os.getenv('RECORDER_IP')  # IP-адрес регистратора
recorder_username = os.getenv('RECORDER_USERNAME')     # Имя пользователя
recorder_password = os.getenv('RECORDER_PASSWORD')  # Пароль
recorder_auth = HTTPDigestAuth(recorder_username, recorder_password)
print(recorder_auth)

last_clusters = {}
