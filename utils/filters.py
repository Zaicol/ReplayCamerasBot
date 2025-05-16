from aiogram.filters import BaseFilter

from aiogram.types import Message

from database import get_by_id, AsyncSessionLocal


class IsUserAdmin(BaseFilter):

    async def __call__(self, message: Message) -> bool:
        async with AsyncSessionLocal() as session:
            user_id = message.from_user.id
            user = await get_by_id(session, 'users', user_id)
            if user is None:
                return False
            return user.access_level >= 2
