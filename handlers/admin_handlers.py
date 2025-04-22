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
    local_session = SessionLocal()
    check_and_create_user(local_session, user_id)

    # Проверяем, существует ли пользователь в БД
    user = get_by_id(local_session, 'users', user_id)
    if not user:
        # Создаем нового пользователя с уровнем доступа 2 (админ)
        new_user = Users(id=user_id, access_level=2)
        local_session.add(new_user)
    else:
        # Обновляем уровень доступа до 2 (админ)
        user.access_level = 2

    local_session.commit()
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
    try:
        create_item(SessionLocal(), 'courts', name=court_name,
                    current_password=generate_password(), previous_password=generate_password(),
                    password_expiration_date=datetime.now() + timedelta(days=1))
    except Exception as e:
        await message.answer(f"Произошла ошибка: {str(e)}")
        logger.error(f"Произошла ошибка добавления корта: {str(e)}", exc_info=True)
        return
    await message.answer(f"Корт '{court_name}' успешно добавлен.")
    await send_courts_list(message)
    await state.clear()


async def send_courts_list(message: types.Message):
    local_session = SessionLocal()
    await check_all_courts_password(local_session)

    # Обновляем данные о кортах в сессии local_session.refresh()
    courts_list = get_all(local_session, 'courts')
    map(local_session.refresh, courts_list)

    response = "Доступные корты:\n"
    response += "ID \\- Название \\(Пароль\\)\n"
    for court in courts_list:
        response += f"`{court.id}` \\- {court.name} \\(`{court.current_password}`\\)\n"
    response += "\n\nДля удаления корта введите `/delete_court \\<ID корта\\>`\\.\n"
    response += "Для обновления пароля корта введите `/update_password \\<ID корта\\>`\\."

    await message.answer(response, parse_mode="MarkdownV2")


@admin_router.message(Command("delete_court"))
async def cmd_delete_court(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("ID корта не указан.")
        return
    court_id = parts[1]
    if not court_id.isdigit():
        await message.answer("ID корта должен быть числом.")
        return
    is_court_deleted = delete_item(SessionLocal(), 'courts', int(court_id))
    if not is_court_deleted:
        await message.answer("Корта с таким ID не существует.")
        return
    await message.answer(f"Корт с ID {court_id} успешно удален.")
    await send_courts_list(message)


@admin_router.message(Command("update_password"))
async def cmd_update_password(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("ID корта не указан.")
        return
    court_id = parts[1]
    with SessionLocal() as local_session:
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


@admin_router.message(DeleteCourtFSM.input_court_id)
async def process_input_court_id(message: types.Message):
    court_id = message.text
    is_court_deleted = delete_item(SessionLocal(), 'courts', int(court_id))
    if not is_court_deleted:
        await message.answer("Корта с таким ID не существует.")
        return
    await message.answer(f"Корт с ID {court_id} успешно удален.")
    await send_courts_list(message)


@admin_router.message(Command("show_courts"))
async def cmd_show_courts(message: types.Message):
    await send_courts_list(message)


# Работа с камерами
@admin_router.message(Command("show_cameras"))
async def cmd_show_cameras(message: types.Message):
    cameras_list = SessionLocal().query(Cameras).all()
    response = "Список камер:\n"
    for camera in cameras_list:
        response += f"{camera.id} - {camera.name}\n"
    await message.answer(response)


# @router.message(Command("add_camera"))
async def cmd_add_camera(message: types.Message):
    await message.answer("Введите название камеры:")
    await AddCameraFSM.input_camera_name.set()


@admin_router.message(AddCameraFSM.input_camera_name)
async def process_input_camera_name(message: types.Message, state: FSMContext):
    camera_name = message.text
    new_camera = Cameras(name=camera_name)
    with SessionLocal() as local_session:
        local_session.add(new_camera)
        local_session.commit()
    await message.answer(f"Камера '{camera_name}' успешно добавлена.")
    await send_cameras_list(message)
    await state.clear()


async def send_cameras_list(message: types.Message):
    cameras_list = SessionLocal().query(Cameras).all()
    response = "Список камер:\n"
    for camera in cameras_list:
        response += f"/show_camera_{camera.id} - {camera.name}\n"
    await message.answer(response)
