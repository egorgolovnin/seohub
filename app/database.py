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
        migrations = [
            "ALTER TABLE ref_links ADD COLUMN IF NOT EXISTS alerts_muted BOOLEAN DEFAULT FALSE",
            "ALTER TABLE ref_link_checks ADD COLUMN IF NOT EXISTS redirect_codes JSON",
            "ALTER TABLE ref_link_checks ADD COLUMN IF NOT EXISTS landing JSON",
        ]
        for sql in migrations:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass
