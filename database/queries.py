import logging
from datetime import datetime, timedelta
from database import SessionLocal
from database.models import *
from utils import generate_password

logger = logging.getLogger(__name__)


def get_model(table: str):
    model = TABLES.get(table)
    if not model:
        raise ValueError(f"Таблица '{table}' не найдена.")
    return model


def get_all(session, table: str):
    return session.query(get_model(table)).all()


def get_by_id(session, table: str, record_id: int):
    return session.query(get_model(table)).filter_by(id=record_id).first()


def get_by_name(session, table: str, name: str):
    return session.query(get_model(table)).filter_by(name=name).first()


def create_item(local_session: SessionLocal, table: str, **kwargs):
    model = get_model(table)
    item = model(**kwargs)
    local_session.add(item)
    local_session.commit()
    local_session.refresh(item)
    return item


def delete_item(local_session: SessionLocal, table: str, record_id: int):
    model = get_model(table)
    item = local_session.query(model).filter_by(id=record_id).first()
    if not item:
        return False
    local_session.delete(item)
    local_session.commit()
    return True


def check_and_create_user(local_session: SessionLocal, user_id: int):
    user = local_session.query(Users).filter_by(id=user_id).first()
    if not user:
        user = Users(id=user_id, access_level=2)
        local_session.add(user)
        local_session.commit()
        local_session.refresh(user)
    return user


async def check_and_set_new_court_password(local_session: SessionLocal, court_input: Courts):
    court = local_session.query(Courts).filter_by(id=court_input.id).first()
    logger.debug(court.password_expiration_date, court.password_expiration_date < datetime.now())
    if court.password_expiration_date < datetime.now():
        new_password = generate_password()
        court.previous_password = court.current_password
        court.current_password = new_password
        # TODO: настроить время
        court.password_expiration_date = datetime.now() + timedelta(days=1)
        local_session.commit()
        local_session.refresh(court)


async def check_password_and_expiration(local_session: SessionLocal, user: Users) -> tuple[bool, datetime | None]:
    if user.court:
        await check_and_set_new_court_password(local_session, user.court)
        return user.court.current_password == user.current_pasword, user.court.password_expiration_date
    return False, None
