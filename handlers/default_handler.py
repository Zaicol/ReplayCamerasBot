from aiogram import types, Router
from aiogram.fsm.context import FSMContext
from handlers.start_handler import cmd_start

default_router = Router()

@default_router.message()
async def default_handler(message: types.Message, state: FSMContext):
    await cmd_start(message, state)
