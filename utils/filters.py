from aiogram.filters import BaseFilter

from aiogram.types import Message
from typing import Any

from database import SessionLocal, get_by_id


class IsUserAdmin(BaseFilter):

    async def __call__(self, message: Message) -> bool:
        local_session = SessionLocal()
        user_id = message.from_user.id
        user = get_by_id(local_session, 'users', user_id)
        if user is None:
            return False
        return user.access_level >= 2
