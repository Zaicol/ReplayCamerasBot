import logging
from datetime import datetime, timedelta

from icecream import ic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import *
from utils import generate_password

logger = logging.getLogger(__name__)


def get_model(table: str):
    model = TABLES.get(table)
    if not model:
        raise ValueError(f"Таблица '{table}' не найдена.")
    return model


async def get_all(session: AsyncSession, table: str):
    model = get_model(table)
    result = await session.execute(select(model))
    return result.scalars().all()


async def get_by_id(session: AsyncSession, table: str, record_id: int):
    model = get_model(table)
    result = await session.execute(
        select(model).where(model.id == record_id)
    )
    return result.scalars().first()


async def get_by_name(session: AsyncSession, table: str, name: str):
    model = get_model(table)
    result = await session.execute(
        select(model).where(model.name == name)
    )
    return result.scalars().first()


# create_item
async def create_item(local_session: AsyncSession, table: str, **kwargs):
    model = get_model(table)
    item = model(**kwargs)
    local_session.add(item)
    await local_session.commit()
    await local_session.refresh(item)
    return item


# delete_item
async def delete_item(local_session: AsyncSession, table: str, record_id: int):
    model = get_model(table)
    result = await local_session.execute(
        select(model).where(model.id == record_id)
    )
    item = result.scalars().first()
    if not item:
        return False
    await local_session.delete(item)
    await local_session.commit()
    return True


# check_and_create_user
async def check_and_create_user(local_session: AsyncSession, user_id: int, access_level: int = 1):
    result = await local_session.execute(
        select(Users).where(Users.id == user_id)
    )
    user = result.scalars().first()
    if not user:
        user = Users(id=user_id, access_level=access_level)
        local_session.add(user)
        await local_session.commit()
        await local_session.refresh(user)
        logger.warn(f"Пользователь {user_id} создан c привилегиями {access_level}. Текущий уровень у юзера: {user.access_level}")
    return user


# check_and_set_court_password
async def check_and_set_court_password(local_session: AsyncSession, court_input: Courts):
    result = await local_session.execute(
        select(Courts).where(Courts.id == court_input.id)
    )
    court = result.scalars().first()
    if not court:
        return None, None

    logger.debug(court.password_expiration_date, court.password_expiration_date < datetime.now())

    if court.password_expiration_date < datetime.now():
        new_password = generate_password()
        court.previous_password = court.current_password
        court.current_password = new_password
        court.password_expiration_date = datetime.now() + timedelta(days=1)
        await local_session.commit()
        await local_session.refresh(court)

    return court.current_password, court.password_expiration_date


# check_all_courts_password
async def check_all_courts_password(local_session: AsyncSession):
    result = await local_session.execute(select(Courts))
    courts = result.scalars().all()
    for court in courts:
        await check_and_set_court_password(local_session, court)


# check_password_and_expiration
async def check_password_and_expiration(local_session: AsyncSession, user: Users) -> tuple[bool, datetime | None]:
    if user.court:
        password, expiration_date = await check_and_set_court_password(local_session, user.court)
        return password == user.current_pasword, expiration_date
    return False, None


# get_last_video
async def get_last_video(local_session: AsyncSession, user_id: int) -> Videos | None:
    result = await local_session.execute(
        select(Users).where(Users.id == user_id)
    )
    user = result.scalars().first()
    ic(user)
    if not user:
        return None

    result = await local_session.execute(
        select(Videos)
        .where(Videos.user_id == user.id)
        .order_by(Videos.timestamp.desc())
        .limit(1)
    )
    video = result.scalars().first()
    ic(video)
    return video


# make_video_public
async def make_video_public(local_session: AsyncSession, video) -> bool:
    video.public = True
    await local_session.commit()
    return True
