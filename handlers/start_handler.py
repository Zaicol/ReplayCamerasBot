from aiogram import types, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from database import check_and_create_user, get_all, AsyncSessionLocal
from utils.keyboards import get_courts_keyboard
from utils.states import SetupFSM
from utils.texts import start_text

start_router = Router()


@start_router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        # Если check_and_create_user — синхронная, то нужно сделать асинхронную версию
        await check_and_create_user(session, message.from_user.id)
        courts_list = await get_all(session, 'courts')

    if not courts_list:
        await message.answer("Нет доступных кортов.")
        return

    await message.answer(
        start_text,
        reply_markup=get_courts_keyboard(courts_list)
    )
    await state.set_state(SetupFSM.select_court)
