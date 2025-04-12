import asyncio
import logging
import os
import random
import string
import subprocess
from datetime import datetime, timedelta
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
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
            # TODO: настроить время
            court.password_expiration_date = datetime.now() + timedelta(days=1)
            session.commit()
            session.refresh(court)


def check_password_and_expiration(user: Users) -> tuple[bool, datetime | None]:
    if user.court:
        check_and_set_new_court_password(user.court)
        return user.court.current_password == user.current_pasword, user.court.password_expiration_date
    return False, None


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


def get_courts_keyboard(courts):
    keyboard = InlineKeyboardMarkup()
    for court in courts:
        # Каждая кнопка имеет callback_data, равное ID корта
        keyboard.add(InlineKeyboardButton(text=court.name, callback_data=f"court_{court.id}"))
    return keyboard


def get_back_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton(text="Назад", callback_data="back"))
    return keyboard


# Запуск захвата видео в отдельном потоке
capture_thread = threading.Thread(target=capture_video, daemon=True)
capture_thread.start()


# Определение состояний
class Setup(StatesGroup):
    select_court = State()
    input_password = State()


# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    session = Session()
    user = session.query(Users).filter_by(id=message.from_user.id).first()
    if not user:
        new_user = Users(id=message.from_user.id, access_level=0)
        session.add(new_user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()

    # Получаем список всех кортов
    courts = session.query(Court).all()
    if not courts:
        await message.answer("Нет доступных кортов.")
        return

    # Отправляем сообщение с кнопками
    await message.answer(
        "Выберите теннисный корт:",
        reply_markup=get_courts_keyboard(courts)
    )
    await state.set_state(Setup.select_court)


@dp.callback_query(Setup.select_court)
async def process_court_selection(callback_query: types.CallbackQuery, state: FSMContext):
    session = Session()

    # Извлекаем ID корта из callback_data
    court_id = int(callback_query.data.split("_")[1])
    court = session.query(Court).filter_by(id=court_id).first()

    if not court:
        await callback_query.message.answer("Такого теннисного корта не существует.")
        return

    # Обновляем данные пользователя
    user = session.query(Users).filter_by(id=callback_query.from_user.id).first()
    user.selected_court_id = court.id
    session.commit()


    # Отправляем подтверждение выбора
    await callback_query.message.answer(
        f"Вы выбрали теннисный корт: {court.name}\n"
        f"Введите пароль:",
        reply_markup=get_back_keyboard()  # Убираем клавиатуру
    )
    await state.set_state(Setup.input_password)

    # Подтверждаем обработку callback_query
    await callback_query.answer()


@dp.callback_query(Setup.input_password)
async def process_back_button(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.answer(
        "Выберите теннисный корт:",
        reply_markup=get_courts_keyboard(Session().query(Court).all())
    )
    await state.set_state(Setup.select_court)


@dp.message(F.text, Setup.input_password)
async def process_input_password(message: types.Message, state: FSMContext):
    session = Session()

    # Получаем пользователя из базы данных
    user = session.query(Users).filter_by(id=message.from_user.id).first()
    if not user or not user.selected_court_id:
        await message.answer("Сначала выберите корт.")
        await state.clear()
        return

    # Получаем выбранный корт
    court = user.court
    if not court:
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте снова.")
        await state.clear()
        return

    # Проверяем введенный пароль
    if court.current_password == message.text:
        # Пароль верный
        user.access_level = 1  # Устанавливаем уровень доступа
        user.current_pasword = message.text
        session.commit()
        await message.answer(
            f"Пароль верный! Добро пожаловать на корт: {court.name}.",
            reply_markup=types.ReplyKeyboardRemove()  # Убираем клавиатуру
        )
        await state.clear()  # Очищаем состояние
    else:
        # Пароль неверный
        await message.answer("Неверный пароль. Попробуйте снова.")


# Сохранение видео
@dp.message(Command("saverec"))
async def cmd_saverec(message: types.Message, state: FSMContext):
    session = Session()
    user = session.query(Users).filter_by(id=message.from_user.id).first()
    if not user or user.access_level < 1:
        await message.answer("У вас нет прав для сохранения видео.")
        return

    password_check, expiration = check_password_and_expiration(user)
    if not password_check:
        await message.answer("Текущий пароль неверен или истёк. Необходимо ввести новый пароль:",
                             reply_markup=get_back_keyboard())
        await state.set_state(Setup.input_password)
        return

    # Получаем буфер видео
    temp_video_path = f"temp_video.mp4"

    # Создаем копию буфера для безопасной итерации
    buffer_copy = list(buffer)  # Копируем содержимое буфера

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

    t_left = expiration - datetime.now()  # Оставшееся время действия пароля
    await message.answer(f"Видео успешно сохранено!\n"
                         f"До конца действия пароля осталось: "
                         f"{t_left.seconds // 60 // 24} ч. {t_left.seconds // 60 % 24} мин. {t_left.seconds % 60} с.")


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
