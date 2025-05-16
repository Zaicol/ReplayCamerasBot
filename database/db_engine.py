from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config.config import DATABASE_URL
from contextlib import asynccontextmanager

# Инициализация SQLAlchemy
engine = create_async_engine(
    DATABASE_URL,
    echo=True,
    future=True
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
    autoflush=False,
    autocommit=False,
)


@asynccontextmanager
async def get_session():
    async with AsyncSessionLocal() as session:
        yield session
