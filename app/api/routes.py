from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.rates import get_cpa_rates, get_pp_conditions, get_rate_for_geo
from app.services.reflinks import check_link
from app.services.stats_analyzer import analyze_stats

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/rates/cpa")
async def api_cpa_rates(geo: str = Query(None), db: AsyncSession = Depends(get_db)):
    rates = await get_cpa_rates(db, geo)
    return {"type": "cpa", "count": len(rates), "data": rates}


@router.get("/rates/{geo}")
async def api_rate_by_geo(geo: str, db: AsyncSession = Depends(get_db)):
    data = await get_rate_for_geo(db, geo)
    if not data:
        return {"error": "GEO not found", "geo": geo}
    return data


@router.get("/pp")
async def api_pp_conditions(name: str = Query(None), db: AsyncSession = Depends(get_db)):
    conditions = await get_pp_conditions(db, name)
    return {"count": len(conditions), "data": conditions}


@router.get("/check-link")
async def api_check_link(url: str):
    result = await check_link(url)
    return result


class StatsRequest(BaseModel):
    program_name: str = ""
    geo: str = ""
    period: str = ""
    model: str = ""
    clicks: int = 0
    registrations: int = 0
    ftd: int = 0
    deposits_sum: float = 0
    ggr: float = 0
    commission: float = 0


@router.post("/analyze-stats")
async def api_analyze_stats(req: StatsRequest):
    stats = req.model_dump()
    analysis = analyze_stats(stats, stats.get("geo", ""))
    return {"stats": stats, "analysis": analysis}


class IoffersRequest(BaseModel):
    telegram: str
    site: str = ""
    comment: str = ""


@router.post("/ioffers-request")
async def api_ioffers_request(req: IoffersRequest):
    from app.bot.main import get_bot
    from app.config import get_settings
    settings = get_settings()
    if settings.admin_chat_id:
        bot = get_bot()
        text = (
            f"📊 <b>Заявка на iOffers</b>\n\n"
            f"👤 Telegram: {req.telegram}\n"
            f"🌐 Сайт: {req.site or 'не указан'}\n"
            f"💬 Комментарий: {req.comment or 'нет'}"
        )
        try:
            await bot.send_message(settings.admin_chat_id, text)
        except Exception:
            pass
    return {"ok": True}
