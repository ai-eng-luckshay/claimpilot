from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.src.config.app_settings import get_settings

settings = get_settings()


def _to_async_url(url: str) -> str:
    return (
        url.replace("postgresql://", "postgresql+asyncpg://")
           .replace("postgres://", "postgresql+asyncpg://")
    )


async_engine = create_async_engine(_to_async_url(settings.database_url), pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
