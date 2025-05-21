import logging
from datetime import datetime, time

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pyotp import random_base32

from utils import update_totp_dict
from database.models import *

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


async def get_count(session: AsyncSession, table: str) -> int:
    model = get_model(table)
    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar()


async def get_videos_by_date_count(session: AsyncSession) -> int:
    # Возвращает количество записанных сегодня видео
    today_start = datetime.combine(datetime.now().date(), time.min)
    result = await session.execute(
        select(func.count())
        .select_from(Videos)
        .where(Videos.timestamp >= today_start)
    )
    return result.scalar()


async def get_first(session: AsyncSession, table: str):
    model = get_model(table)
    result = await session.execute(select(model))
    return result.scalars().first()

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


# update_court_secret
async def update_court_secret(local_session: AsyncSession, court_input: Courts):
    court = court_input
    court.totp_secret = random_base32()
    await local_session.commit()
    await local_session.refresh(court)
    update_totp_dict(court)


# update_all_courts_secret
async def update_all_courts_secret(local_session: AsyncSession):
    result = await local_session.execute(select(Courts))
    courts = result.scalars().all()
    for court in courts:
        await update_court_secret(local_session, court)


# get_last_video
async def get_last_video(local_session: AsyncSession, user_id: int) -> Videos | None:
    result = await local_session.execute(
        select(Users).where(Users.id == user_id)
    )
    user = result.scalars().first()

    if not user:
        return None

    result = await local_session.execute(
        select(Videos)
        .where(Videos.user_id == user.id)
        .order_by(Videos.timestamp.desc())
        .limit(1)
    )
    video = result.scalars().first()

    return video


# make_video_public
async def make_video_public(local_session: AsyncSession, video) -> bool:
    video.public = True
    await local_session.commit()
    return True


async def set_secret_for_all_courts(local_session: AsyncSession):
    result = await local_session.execute(select(Courts))
    courts = result.scalars().all()
    for court in courts:
        if not court.totp_secret:
            await update_court_secret(local_session, court)
