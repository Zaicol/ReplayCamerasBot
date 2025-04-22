import logging
from datetime import datetime

from aiogram import types, F, Bot
from aiogram.dispatcher.dispatcher import Dispatcher
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config.config import VERSION
from database import SessionLocal, get_all, check_and_create_user, get_by_name, get_by_id, \
    check_password_and_expiration, create_item, Users
from utils.cameras import save_video
from utils.keyboards import get_courts_keyboard, get_saverec_keyboard, get_back_keyboard
from utils.states import SetupFSM
from texts import *

logger = logging.getLogger(__name__)


def register_handlers(dp: Dispatcher, bot: Bot):
    @dp.message(lambda message: message.text == "🔙 К выбору корта")
    async def process_back_to_court_button(message: types.Message, state: FSMContext):
        local_session = SessionLocal()
        check_and_create_user(local_session, message.from_user.id)
        await message.answer(
            "Выберите теннисный корт:",
            reply_markup=get_courts_keyboard(get_all(SessionLocal(), 'courts'))
        )
        await state.set_state(SetupFSM.select_court)

    @dp.message(F.text, SetupFSM.select_court)
    async def process_court_selection(message: types.Message, state: FSMContext):
        user_id = message.from_user.id
        local_session = SessionLocal()
        check_and_create_user(local_session, user_id)

        # Извлекаем ID корта из callback_data
        court_name = message.text
        court = get_by_name(local_session, 'courts', court_name)

        if not court:
            await message.answer("Корта с таким именем не существует.")
            return

        # Обновляем данные пользователя
        user = get_by_id(local_session, 'users', user_id)

        if user.selected_court_id:
            logger.debug(user.selected_court_id, court.id, user.current_pasword, user.court.current_password)

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
            reply_markup=get_courts_keyboard(get_all(SessionLocal(), 'courts'))
        )
        await state.set_state(SetupFSM.select_court)

    @dp.message(F.text, SetupFSM.input_password)
    async def process_input_password(message: types.Message, state: FSMContext):
        local_session = SessionLocal()

        # Получаем пользователя из базы данных
        user = get_by_id(local_session, 'users', message.from_user.id)
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
        await message.answer("Начинаю сохранение видео...")
        video_file = await save_video(user, message)

        sent_message = await bot.send_video(chat_id=message.chat.id, video=video_file)

        # Сохранение метаданных в БД
        create_item(
            SessionLocal(), 'videos',
            video_id=sent_message.video.file_id,
            timestamp=datetime.now(),
            user_id=message.from_user.id,
            court_id=user.selected_court_id
        )

    # Сохранение видео
    @dp.message(Command("saverec"))
    @dp.message(lambda message: message.text == "🎥 Сохранить видео")
    async def cmd_saverec(message: types.Message, state: FSMContext):
        local_session = SessionLocal()
        check_and_create_user(local_session, message.from_user.id)
        user = get_by_id(local_session, 'users', message.from_user.id)

        if not user or user.access_level < 1:
            await message.answer("У вас нет прав для сохранения видео.")
            return

        password_check, expiration = check_password_and_expiration(local_session, user)
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
                             f"{t_left.seconds // 60 // 60} ч. "
                             f"{t_left.seconds // 60 % 60} мин. {t_left.seconds % 60} с.",
                             reply_markup=get_saverec_keyboard())

    # Показать список видео
    @dp.message(lambda message: message.text == "Показать видео")
    async def show_videos(message: types.Message):
        local_session = SessionLocal()
        check_and_create_user(local_session, message.from_user.id)
        user = get_by_id(local_session, 'users', message.from_user.id)
        if not user or user.access_level < 1:
            await message.answer("У вас нет прав для просмотра видео.")
            return

        videos = get_all(local_session, 'videos')
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
        local_session = SessionLocal()
        check_and_create_user(local_session, message.from_user.id)
        video_id = int(message.text.split("_")[-1])
        video = get_by_id(local_session, 'videos', video_id)
        if not video:
            await message.answer("Видео не найдено.")
            return

        await bot.send_video(chat_id=message.chat.id, video=video.video_id)
