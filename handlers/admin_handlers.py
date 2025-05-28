import os
import subprocess
from datetime import timedelta

from aiogram import types, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile

from config.config import totp_dict
from database import *
from utils import generate_password, get_totp_for_all_day
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
            await create_item(
                session, 'courts',
                name=court_name,
                secret=generate_password(),
            )
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
        result = await get_all(session, 'courts')
        courts_list = result if isinstance(result, list) else await result.scalars().all()

        # Обновляем объекты в сессии (если нужно)
        for court in courts_list:
            await session.refresh(court)

        response = "Доступные корты:\nID - Название - Пароль\n"
        for court in courts_list:
            response += f"<code>{court.id}</code> - {court.name} - <code>{totp_dict[court.id].now()}</code>\n"
        response += "\n\nДля удаления корта введите <code>/delete_court [ID корта]</code>\n"
        response += "Для обновления пароля корта введите <code>/update_password [ID корта]</code>.\n"
        response += "Для обновления всех паролей введите <code>/update_passwords</code>\n"
        response += "Для получения паролей на сегодня введите <code>/show_passwords [ID корта]</code>"

    await message.answer(response, parse_mode="HTML")


async def send_passwords_for_a_day(message: types.Message, court_id: int, court_name: str):
    passwords_list = await get_totp_for_all_day(court_id)
    today = datetime.now().replace(microsecond=0, second=0, minute=0, hour=0)

    response = f"Пароли для корта «{court_name}» на сегодня:\n"
    for i, password in enumerate(passwords_list, 0):
        hour = today + timedelta(hours=i)
        response += f"{hour.strftime('%H')}:00\-{hour.strftime('%H')}:59 \- `{password}`\n"
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


@admin_router.message(Command("update_passwords"))
async def cmd_update_all_passwords(message: types.Message):
    async with AsyncSessionLocal() as session:
        await update_all_courts_secret(session)
        await session.commit()

    await message.answer(f"Пароли всех кортов успешно обновлены.")
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
        await update_court_secret(session, found_court)
        await session.commit()

    await message.answer(
        f"Пароль корта {found_court.name} с ID {court_id} успешно обновлен."
    )
    await send_passwords_for_a_day(message, court_id, found_court.name)
    await send_courts_list(message)


@admin_router.message(Command("show_passwords"))
async def cmd_show_passwords(message: types.Message):

    async with AsyncSessionLocal() as session:
        if await get_count(session, 'courts') == 1:
            court = await get_first(session, 'courts')
            return await send_passwords_for_a_day(message, court.id, court.name)

    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Необходимо указать правильный ID корта - /show_courts.")
        return
    court_id = int(parts[1])

    async with AsyncSessionLocal() as session:
        found_court = await get_by_id(session, 'courts', court_id)
        if not found_court:
            await message.answer("Корта с таким ID не существует.")
            return

    await send_passwords_for_a_day(message, court_id, found_court.name)


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


@admin_router.message(Command("logs"))
async def cmd_logs(message: types.Message):
    # Отправляет файл logs/bot.log
    log_path = "logs/bot.log"
    if not os.path.exists(log_path):
        await message.answer("Файл логов не найден.")
        return

    try:
        log_file = FSInputFile(log_path)
        await message.answer_document(log_file, caption="Файл логов:")
    except Exception as e:
        await message.answer(f"Ошибка при отправке файла: {e}")


@admin_router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    async with AsyncSessionLocal() as session:
        videos_count = await get_videos_by_date_count(session)
        users_count = await get_count(session, 'users')

    response = f"Количество видео за сегодня: {videos_count}\nОбщее число пользователей: {users_count}"
    await message.answer(response)


@admin_router.message(Command("restart"))
async def restart_command(message: types.Message):
    if not os.path.exists("restart_bot.sh"):
        await message.reply("Файл скрипта перезапуска не найден.")
        return

    await message.reply("Перезапускаю бота...")

    # Запуск скрипта перезапуска
    subprocess.Popen(["/bin/bash", "restart_bot.sh"])
