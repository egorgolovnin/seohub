from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.config import get_settings
import logging

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


engine = create_async_engine(get_settings().database_url, echo=False, pool_size=5, max_overflow=10)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Run migrations for existing tables
    async with engine.begin() as conn:
        try:
            await conn.execute(text(
                "ALTER TABLE ref_links ADD COLUMN IF NOT EXISTS alerts_muted BOOLEAN DEFAULT FALSE"
            ))
            logger.info("Migration: alerts_muted column ensured")
        except Exception as e:
            logger.warning(f"Migration skip: {e}")
