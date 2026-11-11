"""
Database engines.

- The API uses an async engine (asyncpg).
- Celery workers use a sync engine (psycopg), created lazily so the API
  process never opens one.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def _pool_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {}
    return {"pool_size": 5, "max_overflow": 10, "pool_recycle": 1800, "pool_pre_ping": True}


engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG, **_pool_kwargs(settings.DATABASE_URL))
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


@lru_cache
def sync_session_factory() -> sessionmaker[Session]:
    url = settings.SYNC_DATABASE_URL
    return sessionmaker(create_engine(url, **_pool_kwargs(url)), expire_on_commit=False)
