from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from .config import get_settings


def make_engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite"):
        engine = create_async_engine(url, connect_args={"timeout": 30}, poolclass=NullPool)

        # SQLite has no SELECT ... FOR UPDATE. BEGIN IMMEDIATE takes the write lock at the start
        # of every transaction, so concurrent budget reservations serialize instead of racing.
        @event.listens_for(engine.sync_engine, "connect")
        def _connect(dbapi_connection, _record):
            dbapi_connection.isolation_level = None

        @event.listens_for(engine.sync_engine, "begin")
        def _begin(connection):
            connection.exec_driver_sql("BEGIN IMMEDIATE")

        return engine
    return create_async_engine(url, pool_pre_ping=True)


engine = make_engine(get_settings().database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
