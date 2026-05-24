import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.database import Base
from app.models.models import *


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def db_with_rates(db):
    """DB pre-loaded with sample rates data."""
    from app.models.models import GeoRateCPA, GeoRateRS, PPCondition

    db.add_all([
        GeoRateCPA(geo="DE", min_cpa=120, avg_cpa=260, max_cpa=550, data_points=11, sources="cpa.rip", programs="MonkeyTraff"),
        GeoRateCPA(geo="BR", min_cpa=6, avg_cpa=70, max_cpa=120, data_points=8, sources="cpa.rip", programs="Megapari"),
        GeoRateCPA(geo="RU", min_cpa=30, avg_cpa=282, max_cpa=1000, data_points=37, sources="chat, cpa.rip", programs="poshfriends"),
        GeoRateCPA(geo="US", min_cpa=200, avg_cpa=400, max_cpa=800, data_points=3, sources="cpa.rip", programs="HUGE Partners"),
    ])
    db.add_all([
        GeoRateRS(geo="UA", min_rs=50, avg_rs=66, max_rs=80, data_points=6, sources="chat", programs="Royal Partners"),
        GeoRateRS(geo="DE", min_rs=20, avg_rs=30, max_rs=50, data_points=5, sources="cpa.rip", programs="Royal Partners"),
        GeoRateRS(geo="BR", min_rs=20, avg_rs=55, max_rs=80, data_points=9, sources="chat", programs="cpa3snet"),
    ])
    db.add_all([
        PPCondition(name="Royal Partners", geos="DE, BR, RU", cpa_min=None, cpa_max=None, rs_min=60, rs_max=60, records_count=19, source="cpa.rip"),
        PPCondition(name="poshfriends", geos="KZ, RU", cpa_min=50, cpa_max=1000, rs_min=35, rs_max=60, records_count=15, source="tg_channel"),
    ])
    await db.commit()
    return db
