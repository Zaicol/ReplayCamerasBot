from sqlalchemy.ext.asyncio import AsyncEngine

from .models import Base
from .db_engine import engine, AsyncSessionLocal
from .queries import *


async def init_models(engine: AsyncEngine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
