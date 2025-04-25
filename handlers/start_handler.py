from aiogram import types, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from database import SessionLocal, get_all, check_and_create_user
from utils.keyboards import get_courts_keyboard
from utils.states import SetupFSM
from utils.texts import start_text

start_router = Router()


@start_router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    local_session = SessionLocal()
    check_and_create_user(local_session, message.from_user.id)

    # Получаем список всех кортов
    courts_list = get_all(local_session, 'courts')
    if not courts_list:
        await message.answer("Нет доступных кортов.")
        return

    # Отправляем сообщение с кнопками
    await message.answer(
        start_text,
        reply_markup=get_courts_keyboard(courts_list)
    )
    await state.set_state(SetupFSM.select_court)
