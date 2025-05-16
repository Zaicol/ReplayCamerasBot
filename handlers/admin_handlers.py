from aiogram import types, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from database import *
from utils import generate_password
from utils.filters import IsUserAdmin
from utils.states import *

logger = logging.getLogger(__name__)

admin_router = Router()
admin_router.message.filter(IsUserAdmin())


@admin_router.message(Command("set_id"))
async def cmd_set_id(message: types.Message):
    user_id = message.from_user.id
    async with AsyncSessionLocal() as session:
        user = await check_and_create_user(session, user_id, 2)
        user.access_level = 2
        await session.commit()
    await message.answer(f"Ваш ID: {user_id}\nВы добавлены как администратор (уровень доступа 2).")


@admin_router.message(Command("help"))
async def cmd_help(message: types.Message):
    help_message = "Доступные команды:\n"
    help_message += "/start - Запустить бота\n"
    help_message += "/saverec - Сохранить видео\n"
    await message.answer(help_message)


@admin_router.message(Command("add_court"))
async def cmd_add_court(message: types.Message, state: FSMContext):
    await message.answer("Введите название корта:")
    await state.set_state(AddCourtFSM.input_court_name)


@admin_router.message(AddCourtFSM.input_court_name)
async def process_input_court_name(message: types.Message, state: FSMContext):
    court_name = message.text
    async with AsyncSessionLocal() as session:
        try:
            await create_item(session, 'courts',
                              name=court_name,
                              current_password=generate_password(),
                              previous_password=generate_password(),
                              password_expiration_date=datetime.now() + timedelta(days=1))
            await session.commit()
        except Exception as e:
            await message.answer(f"Произошла ошибка: {str(e)}")
            logger.error(f"Ошибка добавления корта: {str(e)}", exc_info=True)
            return
    await message.answer(f"Корт '{court_name}' успешно добавлен.")
    await send_courts_list(message)
    await state.clear()


async def send_courts_list(message: types.Message):
    async with AsyncSessionLocal() as session:
        await check_all_courts_password(session)
        result = await get_all(session, 'courts')
        courts_list = result if isinstance(result, list) else await result.scalars().all()

        # Обновляем объекты в сессии (если нужно)
        for court in courts_list:
            await session.refresh(court)

        response = "Доступные корты:\nID \\- Название \\(Пароль\\)\n"
        for court in courts_list:
            response += f"`{court.id}` \\- {court.name} \\(`{court.current_password}`\\)\n"
        response += "\n\nДля удаления корта введите `/delete_court \\<ID корта\\>`\\.\n"
        response += "Для обновления пароля корта введите `/update_password \\<ID корта\\>`\\."

    await message.answer(response, parse_mode="MarkdownV2")


@admin_router.message(Command("delete_court"))
async def cmd_delete_court(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("ID корта должен быть числом и указан.")
        return
    court_id = int(parts[1])

    async with AsyncSessionLocal() as session:
        is_deleted = await delete_item(session, 'courts', court_id)
        if not is_deleted:
            await message.answer("Корта с таким ID не существует.")
            return
        await session.commit()

    await message.answer(f"Корт с ID {court_id} успешно удален.")
    await send_courts_list(message)


@admin_router.message(Command("update_password"))
async def cmd_update_password(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("ID корта должен быть числом и указан.")
        return
    court_id = int(parts[1])

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Courts).filter_by(id=court_id))
        found_court = result.scalars().first()
        if not found_court:
            await message.answer("Корта с таким ID не существует.")
            return
        new_pass = generate_password()
        found_court.previous_password = found_court.current_password
        found_court.current_password = new_pass
        found_court.password_expiration_date = datetime.now() + timedelta(days=1)
        await session.commit()

    await message.answer(
        f"Пароль корта {found_court.name} с ID {court_id} успешно обновлен.\n"
        f"Новый пароль: `{found_court.current_password}`", parse_mode="MarkdownV2"
    )
    await send_courts_list(message)


@admin_router.message(DeleteCourtFSM.input_court_id)
async def process_input_court_id(message: types.Message):
    court_id = message.text
    async with AsyncSessionLocal() as session:
        is_court_deleted = await delete_item(session, 'courts', int(court_id))
        if not is_court_deleted:
            await message.answer("Корта с таким ID не существует.")
            return
        await session.commit()
    await message.answer(f"Корт с ID {court_id} успешно удален.")
    await send_courts_list(message)


@admin_router.message(Command("show_courts"))
@admin_router.message(Command("show_courts"), SetupFSM.select_court)
async def cmd_show_courts(message: types.Message):
    await send_courts_list(message)


# Работа с камерами
@admin_router.message(Command("show_cameras"))
async def cmd_show_cameras(message: types.Message):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Cameras))
        cameras_list = result.scalars().all()
    response = "Список камер:\n"
    for camera in cameras_list:
        response += f"{camera.id} - {camera.name}\n"
    await message.answer(response)


# @admin_router.message(Command("add_camera"))
# async def cmd_add_camera(message: types.Message):
#     await message.answer("Введите название камеры:")
#     await AddCameraFSM.input_camera_name.set()


@admin_router.message(AddCameraFSM.input_camera_name)
async def process_input_camera_name(message: types.Message, state: FSMContext):
    camera_name = message.text
    new_camera = Cameras(name=camera_name)
    async with AsyncSessionLocal() as session:
        session.add(new_camera)
        await session.commit()
    await message.answer(f"Камера '{camera_name}' успешно добавлена.")
    await send_cameras_list(message)
    await state.clear()


async def send_cameras_list(message: types.Message):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Cameras))
        cameras_list = result.scalars().all()

    response = "Список камер:\n"
    for camera in cameras_list:
        response += f"/show_camera_{camera.id} - {camera.name}\n"
    await message.answer(response)
