import asyncio
import logging
import random
import string
import subprocess
from datetime import datetime, timedelta
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
import cv2
import time
from collections import deque
from models import *
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
import threading
from icecream import ic
from texts import *
from utils.states import *

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Показать видео")]],
    resize_keyboard=True
)

# Параметры записи
BUFFER_DURATION = 40  # Длительность буфера в секундах
FPS = 20  # Частота кадров (примерное значение)
MAX_FRAMES = BUFFER_DURATION * FPS  # Максимальное количество кадров в буфере


def check_and_create_user(user_id: int):
    with Session() as local_session:
        user = local_session.query(Users).filter_by(id=user_id).first()
        if not user:
            user = Users(id=user_id, access_level=2)
            local_session.add(user)
            local_session.commit()
            local_session.refresh(user)
        return user


def generate_password():
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(6))


def check_and_set_new_court_password(court_input: Courts):
    with Session() as local_session:
        court = local_session.query(Courts).filter_by(id=court_input.id).first()
        ic(court.password_expiration_date, court.password_expiration_date < datetime.now())
        if court.password_expiration_date < datetime.now():
            new_password = generate_password()
            court.previous_password = court.current_password
            court.current_password = new_password
            # TODO: настроить время
            court.password_expiration_date = datetime.now() + timedelta(days=1)
            local_session.commit()
            local_session.refresh(court)


def check_password_and_expiration(user: Users) -> tuple[bool, datetime | None]:
    if user.court:
        check_and_set_new_court_password(user.court)
        return user.court.current_password == user.current_pasword, user.court.password_expiration_date
    return False, None


def get_courts_keyboard(courts_list: list[Courts]):
    buttons = [
        KeyboardButton(text=court.name)
        for court in courts_list
    ]
    keyboard = ReplyKeyboardMarkup(keyboard=[buttons])
    return keyboard


def get_back_keyboard():
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 К выбору корта")]])
    return keyboard


def get_saverec_keyboard():
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🎥 Сохранить видео"),
                                              KeyboardButton(text="🔙 К выбору корта")]],
                                   resize_keyboard=True)
    return keyboard


# Фоновая задача для записи видео в буфер
def capture_video(camera: Cameras, buffer: deque):
    # RTSP настройки камеры
    rtsp_url = f"rtsp://{camera.login}:{camera.password}@{camera.ip}:{camera.port}/cam/realmonitor?channel=1&subtype=0"

    cap = cv2.VideoCapture(rtsp_url)
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


with Session() as session:
    cameras = session.query(Cameras).all()

buffers = {camera.id: deque(maxlen=MAX_FRAMES) for camera in cameras}

for camera in cameras:
    # Запуск захвата видео в отдельном потоке
    capture_thread = threading.Thread(target=capture_video, args=(camera, buffers[camera.id]), daemon=True)
    capture_thread.start()


# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    check_and_create_user(message.from_user.id)
    local_session = Session()

    # Получаем список всех кортов
    courts_list = local_session.query(Courts).all()
    if not courts_list:
        await message.answer("Нет доступных кортов.")
        return

    # Отправляем сообщение с кнопками
    await message.answer(
        start_text,
        reply_markup=get_courts_keyboard(courts_list)
    )
    await state.set_state(SetupFSM.select_court)


@dp.message(lambda message: message.text == "🔙 К выбору корта")
async def process_back_to_court_button(message: types.Message, state: FSMContext):
    check_and_create_user(message.from_user.id)
    await message.answer(
        "Выберите теннисный корт:",
        reply_markup=get_courts_keyboard(Session().query(Courts).all())
    )
    await state.set_state(SetupFSM.select_court)


@dp.callback_query(SetupFSM.select_court)
async def process_court_selection(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    check_and_create_user(user_id)
    local_session = Session()

    # Извлекаем ID корта из callback_data
    court_name = message.data
    court = local_session.query(Courts).filter_by(name=court_name).first()

    if not court:
        await message.answer("Корта с таким ID не существует.")
        return

    # Обновляем данные пользователя
    user = local_session.query(Users).filter_by(id=user_id).first()

    if user.selected_court_id:
        ic(user.selected_court_id, court.id, user.current_pasword, user.court.current_password)

    # Если пользователь уже выбрал этот корт, и введённый ранее пароль верный, то пропускаем
    if user.selected_court_id == court.id and user.current_pasword == user.court.current_password:
        await message.answer(
            f"Вы выбрали теннисный корт: {court.name}\n",
            reply_markup=get_saverec_keyboard()
        )
        await state.clear()

        return

    user.selected_court_id = court.id
    local_session.commit()

    # Отправляем подтверждение выбора
    await message.answer(please_enter_password_text,
                         reply_markup=get_back_keyboard()
                         )
    await state.set_state(SetupFSM.input_password)


@dp.callback_query(SetupFSM.input_password)
async def process_back_button(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.answer(
        start_text,
        reply_markup=get_courts_keyboard(Session().query(Courts).all())
    )
    await state.set_state(SetupFSM.select_court)


@dp.message(F.text, SetupFSM.input_password)
async def process_input_password(message: types.Message, state: FSMContext):
    local_session = Session()

    # Получаем пользователя из базы данных
    user = local_session.query(Users).filter_by(id=message.from_user.id).first()
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
        local_session.commit()
        await message.answer(
            right_password_text,
            reply_markup=get_saverec_keyboard()
        )
        await state.clear()  # Очищаем состояние
    else:
        # Пароль неверный
        await message.answer(wrong_password_text)


async def save_and_send_video(user: Users, message: types.Message):
    # Получаем буфер видео
    temp_video_path = f"temp_video.mp4"

    # Создаем копию буфера для безопасной итерации
    buffer_id = user.court.cameras[0].id
    buffer_copy = list(buffers[buffer_id])  # Копируем содержимое буфера

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
    with Session() as local_session:
        video = Videos(
            video_id=sent_message.video.file_id,
            timestamp=datetime.now(),
            user_id=message.from_user.id,
            court_id=user.selected_court_id
        )
        local_session.add(video)
        local_session.commit()


# Сохранение видео
@dp.message(Command("saverec"))
@dp.message(lambda message: message.text == "🎥 Сохранить видео")
async def cmd_saverec(message: types.Message, state: FSMContext):
    check_and_create_user(message.from_user.id)
    with Session() as local_session:
        user = local_session.query(Users).filter_by(id=message.from_user.id).first()

        if not user or user.access_level < 1:
            await message.answer("У вас нет прав для сохранения видео.")
            return

        password_check, expiration = check_password_and_expiration(user)
        if not password_check:
            await message.answer("Текущий пароль неверен или истёк. Необходимо ввести новый пароль:",
                                 reply_markup=get_back_keyboard())
            await state.set_state(SetupFSM.input_password)
            return

        if VERSION != "test":
            await save_and_send_video(user, message)

    t_left = expiration - datetime.now()  # Оставшееся время действия пароля
    await message.answer(f"Видео успешно сохранено!\n"
                         f"До конца действия пароля осталось: "
                         f"{t_left.seconds // 60 // 60} ч. {t_left.seconds // 60 % 60} мин. {t_left.seconds % 60} с.",
                         reply_markup=get_saverec_keyboard())


# Показать список видео
@dp.message(lambda message: message.text == "Показать видео")
async def show_videos(message: types.Message):
    check_and_create_user(message.from_user.id)
    local_session = Session()
    user = local_session.query(Users).filter_by(id=message.from_user.id).first()
    if not user or user.access_level < 1:
        await message.answer("У вас нет прав для просмотра видео.")
        return

    videos = local_session.query(Videos).all()
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
    check_and_create_user(message.from_user.id)
    video_id = int(message.text.split("_")[-1])
    local_session = Session()
    video = local_session.query(Videos).filter_by(id=video_id).first()
    if not video:
        await message.answer("Видео не найдено.")
        return

    await bot.send_video(chat_id=message.chat.id, video=video.video_id)


@dp.message(Command("set_id"))
async def cmd_set_id(message: types.Message):
    check_and_create_user(message.from_user.id)
    user_id = message.from_user.id
    local_session = Session()

    # Проверяем, существует ли пользователь в БД
    user = local_session.query(Users).filter_by(id=user_id).first()
    if not user:
        # Создаем нового пользователя с уровнем доступа 2 (админ)
        new_user = Users(id=user_id, access_level=2)
        local_session.add(new_user)
    else:
        # Обновляем уровень доступа до 2 (админ)
        user.access_level = 2

    local_session.commit()
    await message.answer(f"Ваш ID: {user_id}\nВы добавлены как администратор (уровень доступа 2).")


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_message = "Доступные команды:\n"
    help_message += "/start - Запустить бота\n"
    help_message += "/saverec - Сохранить видео\n"
    await message.answer(help_message)


@dp.message(Command("add_court"))
async def cmd_add_court(message: types.Message, state: FSMContext):
    await message.answer("Введите название корта:")
    await state.set_state(AddCourtFSM.input_court_name)


@dp.message(AddCourtFSM.input_court_name)
async def process_input_court_name(message: types.Message, state: FSMContext):
    court_name = message.text
    new_court = Courts(name=court_name, current_password=generate_password(), previous_password=generate_password(),
                       password_expiration_date=datetime.now() + timedelta(days=1))
    with Session() as local_session:
        local_session.add(new_court)
        local_session.commit()
    await message.answer(f"Корт '{court_name}' успешно добавлен.")
    await send_courts_list(message)
    await state.clear()


async def send_courts_list(message: types.Message):
    courts_list = Session().query(Courts).all()
    response = "Доступные корты:\n"
    response += "ID \\- Название \\(Пароль\\)\n"
    for court in courts_list:
        response += f"`{court.id}` \\- {court.name} \\(`{court.current_password}`\\)\n"
    response += "\n\nДля удаления корта введите `/delete_court \\<ID корта\\>`\\.\n"
    response += "Для обновления пароля корта введите `/update_password \\<ID корта\\>`\\."
    await message.answer(response, parse_mode="MarkdownV2")


@dp.message(Command("delete_court"))
async def cmd_delete_court(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("ID корта не указан.")
        return
    court_id = parts[1]
    with Session() as local_session:
        found_court = local_session.query(Courts).filter_by(id=court_id).first()
        if not found_court:
            await message.answer("Корта с таким ID не существует.")
            return
        local_session.delete(found_court)
        local_session.commit()
    await message.answer(f"Корт с ID {court_id} успешно удален.")
    await send_courts_list(message)


@dp.message(Command("update_password"))
async def cmd_update_password(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("ID корта не указан.")
        return
    court_id = parts[1]
    with Session() as local_session:
        found_court = local_session.query(Courts).filter_by(id=court_id).first()
        if not found_court:
            await message.answer("Корта с таким ID не существует.")
            return
        found_court.current_password = generate_password()
        found_court.previous_password = found_court.current_password
        found_court.password_expiration_date = datetime.now() + timedelta(days=1)
        local_session.commit()
        await message.answer(f"Пароль корта {found_court.name} с ID {court_id} успешно обновлен.\n"
                             f"Новый пароль: `{found_court.current_password}`")
    await send_courts_list(message)


@dp.message(DeleteCourtFSM.input_court_id)
async def process_input_court_id(message: types.Message):
    court_id = message.text
    with Session() as local_session:
        found_court = local_session.query(Courts).filter_by(id=court_id).first()
        if not found_court:
            await message.answer("Корта с таким ID не существует.")
            return
        local_session.delete(found_court)
        local_session.commit()
    await message.answer(f"Корт с ID {court_id} успешно удален.")
    await send_courts_list(message)


@dp.message(Command("show_courts"))
async def cmd_show_courts(message: types.Message):
    await send_courts_list(message)


# Работа с камерами
@dp.message(Command("show_cameras"))
async def cmd_show_cameras(message: types.Message):
    cameras_list = Session().query(Cameras).all()
    response = "Список камер:\n"
    for camera in cameras_list:
        response += f"{camera.id} - {camera.name}\n"
    await message.answer(response)


# @dp.message(Command("add_camera"))
async def cmd_add_camera(message: types.Message):
    await message.answer("Введите название камеры:")
    await AddCameraFSM.input_camera_name.set()


@dp.message(AddCameraFSM.input_camera_name)
async def process_input_camera_name(message: types.Message, state: FSMContext):
    camera_name = message.text
    new_camera = Cameras(name=camera_name)
    with Session() as local_session:
        local_session.add(new_camera)
        local_session.commit()
    await message.answer(f"Камера '{camera_name}' успешно добавлена.")
    await send_cameras_list(message)
    await state.clear()


async def send_cameras_list(message: types.Message):
    cameras_list = Session().query(Cameras).all()
    response = "Список камер:\n"
    for camera in cameras_list:
        response += f"/show_camera_{camera.id} - {camera.name}\n"
    await message.answer(response)


# Запуск бота
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    with Session() as start_session:
        courts = start_session.query(Courts).all()
        if not courts:
            test_court = Courts(name="Тестовый корт", current_password="qwe", previous_password="qwe",
                                password_expiration_date=datetime.now() - timedelta(days=1))
            start_session.add(test_court)
            start_session.commit()
    asyncio.run(main())
