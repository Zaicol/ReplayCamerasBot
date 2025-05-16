import os

from aiogram import types, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from utils.cameras import save_video
from utils.keyboards import *
from utils.states import SetupFSM
from database import *
from utils.texts import *

from config.config import bot

logger = logging.getLogger(__name__)

user_router = Router()


@user_router.message(Command("set_id_temp"))
async def cmd_set_id(message: types.Message):
    user_id = message.from_user.id
    async with AsyncSessionLocal() as local_session:
        user = await check_and_create_user(local_session, user_id, 2)
        user.access_level = 2
        await local_session.commit()
        await message.answer(f"Ваш ID: {user_id}\nВы добавлены как администратор (уровень доступа 2).")


@user_router.message(lambda message: message.text == back_text)
async def process_back_to_court_button(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        await check_and_create_user(session, message.from_user.id)
        courts = await get_all(session, 'courts')

    await message.answer(
        start_text,
        reply_markup=get_courts_keyboard(courts)
    )
    await state.set_state(SetupFSM.select_court)


@user_router.message(F.text, SetupFSM.select_court)
async def process_court_selection(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        await check_and_create_user(session, user_id)
        await check_all_courts_password(session)

        court_name = message.text
        court = await get_by_name(session, 'courts', court_name)

        if not court:
            await message.answer("Корта с таким именем не существует.")
            return

        user = await get_by_id(session, 'users', user_id)

        if user.selected_court_id:
            logger.debug(user.selected_court_id, court.id, user.current_pasword, user.court.current_password)

        if user.selected_court_id == court.id and user.current_pasword == user.court.current_password:
            await message.answer(
                f"Вы выбрали теннисный корт: {court.name}\n",
                reply_markup=get_saverec_short_keyboard()
            )
            await state.set_state(SetupFSM.save_video)
            return

        user.selected_court_id = court.id
        await session.commit()

    await message.answer(
        please_enter_password_text,
        reply_markup=get_back_keyboard()
    )
    await state.set_state(SetupFSM.input_password)


@user_router.callback_query(SetupFSM.input_password)
async def process_back_button(callback_query: types.CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        courts = await get_all(session, 'courts')

    await callback_query.message.answer(
        start_text,
        reply_markup=get_courts_keyboard(courts)
    )
    await state.set_state(SetupFSM.select_court)


@user_router.message(F.text, SetupFSM.input_password)
async def process_input_password(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_by_id(session, 'users', message.from_user.id)
        if not user or not user.selected_court_id:
            await message.answer("Сначала выберите корт.")
            await state.clear()
            return

        court = user.court
        if not court:
            await message.answer("Произошла ошибка. Пожалуйста, попробуйте снова.")
            await state.clear()
            return

        if court.current_password == message.text:
            user.access_level = 1
            user.current_pasword = message.text
            await session.commit()

            await message.answer(
                right_password_text,
                reply_markup=get_saverec_short_keyboard()
            )
            await state.set_state(SetupFSM.save_video)
        else:
            await message.answer(wrong_password_text)


async def save_and_send_video(user: Users, message: types.Message) -> bool:
    await message.answer(saving_video_text)
    video_file = await save_video(user, message)

    if video_file is None:
        await message.answer(error_text)
        return False

    sent_message = await bot.send_video(chat_id=message.chat.id, video=video_file)

    async with AsyncSessionLocal() as session:
        await create_item(
            session, 'videos',
            video_id=sent_message.video.file_id,
            timestamp=datetime.now(),
            user_id=message.from_user.id,
            court_id=user.selected_court_id
        )
        await session.commit()

    try:
        os.remove(video_file.path)
    except Exception as e:
        logging.error(f"Ошибка при удалении файла: {e}")

    return True


@user_router.message(Command("saverec"))
@user_router.message(lambda message: message.text in (save_video_text, yes_text, no_text), SetupFSM.save_video)
async def cmd_saverec(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        await check_and_create_user(session, message.from_user.id)
        user = await get_by_id(session, 'users', message.from_user.id)

        if not user or user.access_level < 1:
            await message.answer("У вас нет прав для сохранения видео.")
            return

        if message.text == no_text:
            await message.answer("Хорошо, мы не будем публиковать видео")
            return

        if message.text == yes_text:
            last_video = await get_last_video(session, message.from_user.id)
            ic(last_video)
            if last_video is None:
                await message.answer(error_text)
                return

            if not await make_video_public(session, last_video):
                await message.answer(error_text)
                return

            await message.answer(public_text)
            return

        password_check, expiration = await check_password_and_expiration(session, user)
        if not password_check:
            await message.answer(
                "Текущий пароль неверен или истёк. Необходимо ввести новый пароль:",
                reply_markup=get_back_keyboard()
            )
            await state.set_state(SetupFSM.input_password)
            return

    all_good = await save_and_send_video(user, message)
    if not all_good:
        return

    t_left = expiration - datetime.now()
    await message.answer(
        make_public_text + "\n" +
        f"До конца действия пароля осталось: "
        f"{t_left.seconds // 3600} ч. "
        f"{(t_left.seconds % 3600) // 60} мин. {t_left.seconds % 60} с.",
        reply_markup=get_saverec_full_keyboard()
    )


# Показать список видео
@user_router.message(lambda message: message.text == "Показать видео")
async def show_videos(message: types.Message):
    async with AsyncSessionLocal() as session:
        await check_and_create_user(session, message.from_user.id)
        user = await get_by_id(session, 'users', message.from_user.id)
        if not user or user.access_level < 1:
            await message.answer("У вас нет прав для просмотра видео.")
            return

        videos = await get_all(session, 'videos')
        if not videos:
            await message.answer("Нет доступных видео.")
            return

        response = "Список видео:\n"
        for video in videos:
            response += f"/show_video_{video.id} - {video.description} ({video.timestamp})\n"
        await message.answer(response)


# Показать конкретное видео
@user_router.message(F.text.regexp(r'^/show_video_(\d+)$'))
async def show_specific_video(message: types.Message):
    async with AsyncSessionLocal() as session:
        await check_and_create_user(session, message.from_user.id)
        video_id = int(message.text.split("_")[-1])
        video = await get_by_id(session, 'videos', video_id)
        if not video:
            await message.answer("Видео не найдено.")
            return

        await bot.send_video(chat_id=message.chat.id, video=video.video_id)

