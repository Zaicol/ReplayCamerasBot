import asyncio
import logging
import os
import random
import string
import subprocess
from datetime import datetime, timedelta
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from sqlalchemy.exc import IntegrityError
import cv2
import time
from collections import deque
from models import *
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
import threading

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
API_TOKEN = os.getenv('API_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация SQLAlchemy
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)

# Инициализация бота
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# RTSP настройки камеры
CAMERA_IP = "192.168.10.109"
CAMERA_USER = "admin"
CAMERA_PASS = "St604433"
RTSP_PORT = 554
RTSP_URL = f"rtsp://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:{RTSP_PORT}/cam/realmonitor?channel=1&subtype=0"

# Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Показать видео")]],
    resize_keyboard=True
)

# Параметры записи
BUFFER_DURATION = 40  # Длительность буфера в секундах
FPS = 20  # Частота кадров (примерное значение)
MAX_FRAMES = BUFFER_DURATION * FPS  # Максимальное количество кадров в буфере

# Циклический буфер
buffer = deque(maxlen=MAX_FRAMES)


def generate_password():
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(6))


def check_and_set_new_court_password(court: Court):
    if court.password_expiration_date < datetime.now():
        with Session() as session:
            new_password = generate_password()
            court.previous_password = court.current_password
            court.current_password = new_password
            court.password_expiration_date = datetime.now() + timedelta(days=1)
            session.commit()


def check_password_and_time(user: Users):
    if user.court:
        if user.court.password_expiration_date < datetime.now():

        return user.court.current_password == user.current_pasword
    return False


# Фоновая задача для записи видео в буфер
def capture_video():
    global buffer
    cap = cv2.VideoCapture(RTSP_URL)
    if not cap.isOpened():
        logging.error("Ошибка: Не удалось подключиться к видеопотоку.")
        return

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            logging.error("Ошибка: Не удалось получить кадр из видеопотока. Повторная попытка...")
            time.sleep(1)
            continue

        # Добавляем кадр в буфер
        buffer.append(frame)


# Запуск захвата видео в отдельном потоке
capture_thread = threading.Thread(target=capture_video, daemon=True)
capture_thread.start()


# Определение состояний
class Form(StatesGroup):
    waiting_for_description = State()  # Состояние ожидания описания


# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    session = Session()
    user = session.query(Users).filter_by(id=message.from_user.id).first()
    if not user:
        new_user = Users(id=message.from_user.id, access_level=0)
        session.add(new_user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
    await message.answer("Добро пожалуйста!", reply_markup=main_menu)


# Сохранение видео
@dp.message(Command("saverec"))
async def cmd_saverec(message: types.Message, state: FSMContext):
    session = Session()
    user = session.query(Users).filter_by(id=message.from_user.id).first()
    if not user or user.access_level < 2:
        await message.answer("У вас нет прав для сохранения видео.")
        return

    temp_video_path = f"temp_video.mp4"

    # Создаем копию буфера для безопасной итерации
    buffer_copy = list(buffer)  # Копируем содержимое буфера [[9]]

    if len(buffer_copy) == 0:
        await message.answer("Буфер пуст. Нечего сохранять.")
        return

    # Получаем параметры видео из первого кадра
    frame_width = buffer_copy[0].shape[1]
    frame_height = buffer_copy[0].shape[0]

    # Записываем видео в файл
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(temp_video_path, fourcc, FPS, (frame_width, frame_height))

    for frame in buffer_copy:  # Итерируемся по копии буфера
        out.write(frame)

    out.release()

    # Транскодирование видео в H.264
    transcoded_video_path = f"transcoded_temp_video.mp4"
    subprocess.run([
        "ffmpeg",
        "-i", temp_video_path,
        "-c:v", "libx264",  # Кодек H.264
        "-preset", "fast",
        transcoded_video_path
    ])

    # Отправка видео в Telegram
    video_file = FSInputFile(transcoded_video_path)
    sent_message = await bot.send_video(chat_id=message.chat.id, video=video_file)

    # Сохранение метаданных в БД
    session = Session()
    video = Videos(
        video_id=sent_message.video.file_id,
        timestamp=datetime.now(),
        user_id=message.from_user.id,
        court_id=user.selected_court_id
    )
    session.add(video)
    session.commit()

    await message.answer("Видео успешно сохранено!")


# Показать список видео
@dp.message(lambda message: message.text == "Показать видео")
async def show_videos(message: types.Message):
    session = Session()
    user = session.query(Users).filter_by(id=message.from_user.id).first()
    if not user or user.access_level < 1:
        await message.answer("У вас нет прав для просмотра видео.")
        return

    videos = session.query(Videos).all()
    if not videos:
        await message.answer("Нет доступных видео.")
        return

    response = "Список видео:\n"
    for video in videos:
        response += f"/show_video_{video.id} - {video.description} ({video.timestamp})\n"
    await message.answer(response)


# Показать конкретное видео
@dp.message(F.text.regexp(r'^/show_video_(\d+)$'))
async def show_specific_video(message: types.Message):
    video_id = int(message.text.split("_")[-1])
    session = Session()
    video = session.query(Videos).filter_by(id=video_id).first()
    if not video:
        await message.answer("Видео не найдено.")
        return

    await bot.send_video(chat_id=message.chat.id, video=video.video_id)


# Команда /set_id
@dp.message(Command("set_id"))
async def cmd_set_id(message: types.Message):
    user_id = message.from_user.id
    session = Session()

    # Проверяем, существует ли пользователь в БД
    user = session.query(Users).filter_by(id=user_id).first()
    if not user:
        # Создаем нового пользователя с уровнем доступа 2 (админ)
        new_user = Users(id=user_id, access_level=2)
        session.add(new_user)
    else:
        # Обновляем уровень доступа до 2 (админ)
        user.access_level = 2

    session.commit()
    await message.answer(f"Ваш ID: {user_id}\nВы добавлены как администратор (уровень доступа 2).")


# Запуск бота
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
